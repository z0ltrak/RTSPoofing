"""
Localhost HTTP streaming server for the NVR's browser viewer.

Serves two things on the port the NVR picks:

    GET /         → the viewer page (NVR/web/index.html)
    GET /stream   → a long-lived chunked response carrying a framed binary
                    protocol the viewer parses with fetch().body.getReader().

Wire format on /stream — each message is self-delimited:

    [4B length BE, including the type byte]
    [1B type]
    [payload]

Types:

    0  CONFIG   — JSON (utf-8). {codec, sps[], pps[], vps[], epoch}
                  SPS/PPS/VPS are base64-encoded raw NAL units (no start code).
                  Browser calls VideoDecoder.configure() on each new epoch.
    1  VIDEO    — one complete H.264/H.265 access unit:
                  [1B is_keyframe][annex-b NAL... with 00 00 00 01 start codes]
                  Browser builds an EncodedVideoChunk and calls decode().
    2  STATUS   — JSON (utf-8). Free-form state blob for the stats panel.

Flow control:

    * The server fans one broadcast out to N connected browser clients.
    * Each client has its own bounded queue; VIDEO drops on queue-full
      (preserves liveness — a slow browser doesn't stall the RTSP side).
    * CONFIG and STATUS are also cached as "latest known" and resent to
      every newly-connecting client so a fresh browser gets the current
      stream parameters without waiting for the camera to re-emit SPS/PPS.

Design keeps everything on stdlib: http.server.ThreadingHTTPServer + manual
HTTP-chunked framing on top. No pip deps, no websocket handshake, no asyncio.
"""

from __future__ import annotations

import base64
import http.server
import json
import logging
import socket
import struct
import threading
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Optional


log = logging.getLogger("nvr.web")

WEB_DIR = Path(__file__).resolve().parent / "web"

MSG_CONFIG = 0
MSG_VIDEO = 1
MSG_STATUS = 2


def _frame(msg_type: int, payload: bytes) -> bytes:
    """[4B length BE including type byte][1B type][payload]."""
    return struct.pack("!I", len(payload) + 1) + bytes([msg_type]) + payload


class _ClientChannel:
    """
    One connected browser's view of the broadcast.

    VIDEO is lossy: on queue-full we drop the oldest video frame to keep the
    newest flowing — a slow client never backs the live RTSP side up. CONFIG
    and STATUS are retained-latest; they're small, infrequent, and losing one
    would leave the viewer stuck or showing stale text.
    """

    def __init__(self, maxsize: int = 512) -> None:
        self._q: "Queue[bytes]" = Queue(maxsize=maxsize)
        self._closed = threading.Event()

    def push_video(self, msg: bytes) -> None:
        try:
            self._q.put_nowait(msg)
        except Full:
            try:
                self._q.get_nowait()
            except Empty:
                pass
            try:
                self._q.put_nowait(msg)
            except Full:
                pass

    def push_control(self, msg: bytes) -> None:
        """CONFIG/STATUS — small, must-not-drop."""
        try:
            self._q.put(msg, timeout=0.1)
        except Full:
            # Last-resort: a client is completely stuck. Drain and retry so
            # control messages still land; otherwise the browser is wedged.
            try:
                self._q.get_nowait()
            except Empty:
                pass
            try:
                self._q.put_nowait(msg)
            except Full:
                pass

    def iter(self):
        """Yield framed messages until the client disconnects."""
        while not self._closed.is_set():
            try:
                yield self._q.get(timeout=0.5)
            except Empty:
                continue

    def close(self) -> None:
        self._closed.set()
        # Unblock any pending get() in iter().
        try:
            self._q.put_nowait(b"")
        except Full:
            pass


class _ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    """TCP server with SO_REUSEADDR and daemon threads for fast shutdown."""

    allow_reuse_address = True
    daemon_threads = True


class NvrWebServer:
    """
    Localhost HTTP streaming server.

    Usage:
        srv = NvrWebServer(host="127.0.0.1", port=8080)
        srv.start()
        srv.publish_config(codec="H264", sps=[...], pps=[...])
        srv.publish_video(access_unit_bytes, is_keyframe=True)
        srv.publish_status({"ssrc": "0x…", "fps": 25, "state": "streaming"})
        srv.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self._clients: list[_ClientChannel] = []
        self._clients_lock = threading.Lock()
        self._latest_config: Optional[bytes] = None
        self._latest_status: Optional[bytes] = None
        self._epoch = 0
        self._server: Optional[_ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle ----

    def start(self) -> None:
        handler_cls = self._make_handler_class()
        try:
            self._server = _ThreadingHTTPServer((self.host, self.port), handler_cls)
        except OSError as e:
            raise RuntimeError(f"cannot bind {self.host}:{self.port}: {e}") from e
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="nvr-web", daemon=True
        )
        self._thread.start()
        log.info("web viewer at http://%s:%d/", self.host, self.port)

    def stop(self) -> None:
        with self._clients_lock:
            for c in self._clients:
                c.close()
            self._clients.clear()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # ---- publish API, called from the RTSP loop ----

    def publish_config(
        self,
        codec: str,
        sps: list[bytes],
        pps: list[bytes],
        vps: Optional[list[bytes]] = None,
    ) -> None:
        """New (or refreshed) codec parameter sets. Bumps the epoch."""
        self._epoch += 1
        payload = json.dumps({
            "codec": codec,
            "sps": [base64.b64encode(x).decode("ascii") for x in sps],
            "pps": [base64.b64encode(x).decode("ascii") for x in pps],
            "vps": [base64.b64encode(x).decode("ascii") for x in (vps or [])],
            "epoch": self._epoch,
        }, separators=(",", ":")).encode("utf-8")
        msg = _frame(MSG_CONFIG, payload)
        with self._clients_lock:
            self._latest_config = msg
            for c in self._clients:
                c.push_control(msg)

    def publish_video(self, access_unit: bytes, is_keyframe: bool) -> None:
        """One complete access unit of Annex-B NALUs."""
        if not access_unit:
            return
        payload = bytes([1 if is_keyframe else 0]) + access_unit
        msg = _frame(MSG_VIDEO, payload)
        with self._clients_lock:
            for c in self._clients:
                c.push_video(msg)

    def publish_status(self, status: dict) -> None:
        payload = json.dumps(status, separators=(",", ":")).encode("utf-8")
        msg = _frame(MSG_STATUS, payload)
        with self._clients_lock:
            self._latest_status = msg
            for c in self._clients:
                c.push_control(msg)

    @property
    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    # ---- internal: client registration ----

    def _add_client(self, c: _ClientChannel) -> None:
        with self._clients_lock:
            # Prime the new client with the latest known state so a browser
            # that just opened the tab doesn't have to wait for the next
            # keyframe boundary to see the stream parameters.
            if self._latest_config is not None:
                c.push_control(self._latest_config)
            if self._latest_status is not None:
                c.push_control(self._latest_status)
            self._clients.append(c)
        log.info("web client connected (total=%d)", len(self._clients))

    def _remove_client(self, c: _ClientChannel) -> None:
        with self._clients_lock:
            try:
                self._clients.remove(c)
            except ValueError:
                pass
        c.close()
        log.info("web client disconnected (total=%d)", len(self._clients))

    # ---- HTTP handler ----

    def _make_handler_class(server_self):
        class Handler(http.server.BaseHTTPRequestHandler):
            # http.server's default log is noisy; log at DEBUG via our logger.
            def log_message(self, format: str, *args) -> None:  # noqa: A002, ARG002
                log.debug("http %s - %s", self.address_string(), format % args)

            def do_GET(self) -> None:  # noqa: N802
                if self.path in ("/", "/index.html"):
                    self._serve_static("index.html", "text/html; charset=utf-8")
                elif self.path == "/stream":
                    self._serve_stream()
                else:
                    self.send_error(404, "not found")

            def _serve_static(self, name: str, content_type: str) -> None:
                path = (WEB_DIR / name).resolve()
                if WEB_DIR.resolve() not in path.parents and path != (WEB_DIR / name).resolve():
                    self.send_error(403, "forbidden")
                    return
                try:
                    data = path.read_bytes()
                except OSError:
                    self.send_error(404, "not found")
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _serve_stream(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Cache-Control", "no-store")
                # Disable proxy / nginx buffering if someone sticks one in
                # front; harmless on direct localhost.
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                # Shrink Nagle's effect: we want each frame on the wire ASAP.
                try:
                    self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass

                client = _ClientChannel()
                server_self._add_client(client)
                try:
                    for msg in client.iter():
                        if not msg:
                            continue
                        chunk_header = f"{len(msg):x}\r\n".encode("ascii")
                        try:
                            self.wfile.write(chunk_header)
                            self.wfile.write(msg)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                finally:
                    server_self._remove_client(client)
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass

        return Handler
