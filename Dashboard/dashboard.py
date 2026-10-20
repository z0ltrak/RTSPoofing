#!/usr/bin/env python3
"""
RTSPoofing proxy dashboard — localhost web GUI to drive the Rust proxy
without touching the terminal mid-demo.

Behaviour:

    * Serves a single-page viewer at /, in Dashboard/web/index.html.
    * Spawns, stops and restarts the `rtspoofing` binary with the arguments
      the page sent (record/inject mode, camera host/port, listen port,
      capture file, inject tunables, tcpkill opts…).
    * Fans the proxy's stdout+stderr out to any connected browser via a
      long-lived chunked response at /api/logs — same pattern as the NVR
      viewer's /stream.
    * Keeps a ring buffer of the last N log lines so a fresh connect can
      paint recent history immediately.
    * All stdlib — no pip install. The only external dependency is the
      proxy binary itself; path is passed with --proxy-binary.

Scope:

    * One proxy process at a time per dashboard. Starting a new one with a
      process already running stops the running one first.
    * Only loopback by default; bind host is overridable with --host for
      lab-only remote access. The dashboard launches arbitrary subprocesses
      with user-supplied arguments, so putting it on 0.0.0.0 means handing
      shell access to anyone on the LAN. Document loudly.

Usage:

    python3 dashboard.py --proxy-binary ../RE/target/release/rtspoofing
    # then open http://127.0.0.1:8090/
"""

from __future__ import annotations

import argparse
import http.server
import json
import logging
import os
import shlex
import signal
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Optional


log = logging.getLogger("dashboard")

WEB_DIR = Path(__file__).resolve().parent / "web"


# ---------- Proxy process controller ----------

class ProxyController:
    """
    Owns at most one running `rtspoofing` subprocess. Thread-safe; the HTTP
    handler threads and the log-reader threads all touch it concurrently.
    """

    LOG_RING = 2000  # recent lines kept for new log subscribers

    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._cmdline: Optional[list[str]] = None
        self._started_at: float = 0.0

        # Log fan-out: ring buffer + per-subscriber queues.
        self._log_lock = threading.Lock()
        self._log_ring: list[dict] = []
        self._log_subs: list["Queue[dict]"] = []

    # ---- public API ----

    def status(self) -> dict:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            return {
                "running": bool(running),
                "pid": self._proc.pid if running else None,
                "uptime": round(time.time() - self._started_at, 1) if running else 0,
                "cmdline": list(self._cmdline) if self._cmdline else None,
                "exit_code": self._proc.returncode if self._proc and not running else None,
                "binary": str(self.binary),
            }

    def start(self, args: dict) -> dict:
        """
        Spawn a new proxy. If one is already running it's stopped first,
        so a POST /api/start always leaves exactly one proxy running (or
        none, if it crashed on launch).
        """
        argv = self._build_argv(args)
        with self._lock:
            self._stop_locked(reason="restart")
            self._emit("dash", "spawning: " + " ".join(shlex.quote(a) for a in argv))
            try:
                proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,                  # line-buffered
                    text=True,
                    errors="replace",
                    # New session so Ctrl-C on the dashboard doesn't propagate
                    # to the proxy; we manage its lifetime explicitly.
                    start_new_session=True,
                )
            except FileNotFoundError as e:
                self._emit("dash", f"spawn failed: {e}")
                raise
            self._proc = proc
            self._cmdline = argv
            self._started_at = time.time()
            # Readers: one per stream, daemon so interpreter exit doesn't block.
            threading.Thread(target=self._reader, args=(proc.stdout, "out"), daemon=True).start()
            threading.Thread(target=self._reader, args=(proc.stderr, "err"), daemon=True).start()
            threading.Thread(target=self._wait_exit, args=(proc,), daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_locked(reason="user")
        return self.status()

    # ---- log API ----

    def subscribe(self) -> "Queue[dict]":
        """Return a Queue the caller reads log entries from until unsubscribe."""
        q: "Queue[dict]" = Queue(maxsize=1024)
        with self._log_lock:
            # Prime with recent history so a new connection has context.
            for entry in self._log_ring[-200:]:
                try:
                    q.put_nowait(entry)
                except Full:
                    break
            self._log_subs.append(q)
        return q

    def unsubscribe(self, q: "Queue[dict]") -> None:
        with self._log_lock:
            try:
                self._log_subs.remove(q)
            except ValueError:
                pass

    # ---- internals ----

    def _stop_locked(self, reason: str) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._emit("dash", f"stopping proxy (pid={self._proc.pid}, reason={reason})")
            try:
                # SIGTERM to the whole process group so any child tcpkill
                # dies with it.
                pg = os.getpgid(self._proc.pid)
                os.killpg(pg, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._emit("dash", "SIGTERM timed out; sending SIGKILL")
                try:
                    pg = os.getpgid(self._proc.pid)
                    os.killpg(pg, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    self._proc.kill()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        # Leave self._proc assigned so status() can still report the final
        # exit code the next time anyone asks — _start_locked overwrites it.

    def _reader(self, stream, label: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                line = line.rstrip("\n")
                if not line:
                    continue
                self._emit(label, line)
        except (ValueError, OSError):
            # Stream closed under us during shutdown; expected.
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _wait_exit(self, proc: subprocess.Popen) -> None:
        rc = proc.wait()
        self._emit("dash", f"proxy exited (pid={proc.pid}, rc={rc})")

    def _emit(self, src: str, line: str) -> None:
        entry = {"ts": time.time(), "src": src, "line": line}
        with self._log_lock:
            self._log_ring.append(entry)
            if len(self._log_ring) > self.LOG_RING:
                del self._log_ring[: len(self._log_ring) - self.LOG_RING + 200]
            for sub in list(self._log_subs):
                try:
                    sub.put_nowait(entry)
                except Full:
                    # Slow consumer: drop oldest to keep live tail flowing.
                    try:
                        sub.get_nowait()
                    except Empty:
                        pass
                    try:
                        sub.put_nowait(entry)
                    except Full:
                        pass

    # ---- argv builder ----
    #
    # Keep this in lock-step with RE/src/main.rs Cli. Only pass flags the
    # user actually set; leave the rest to the proxy's own defaults so a
    # typo in the dashboard doesn't silently change proxy behaviour.

    _MODES = {"record", "inject"}
    _LOG_LEVELS = {"trace", "debug", "info", "warn", "error"}

    def _build_argv(self, args: dict) -> list[str]:
        mode = str(args.get("mode", "")).lower()
        if mode not in self._MODES:
            raise ValueError(f"mode must be one of {sorted(self._MODES)}, got {mode!r}")

        argv: list[str] = [str(self.binary), "--mode", mode]

        host = str(args.get("camera_host", "")).strip()
        if not host:
            raise ValueError("camera_host is required")
        argv += ["--camera-host", host]

        def _opt_num(flag: str, key: str, cast) -> None:
            v = args.get(key)
            if v is None or v == "":
                return
            try:
                argv.extend([flag, str(cast(v))])
            except (TypeError, ValueError) as e:
                raise ValueError(f"{key}: {e}") from None

        def _opt_str(flag: str, key: str) -> None:
            v = args.get(key)
            if v is None:
                return
            s = str(v).strip()
            if s:
                argv.extend([flag, s])

        def _opt_flag(flag: str, key: str) -> None:
            if bool(args.get(key)):
                argv.append(flag)

        _opt_str("--bind",            "bind")
        _opt_num("--listen-port",     "listen_port",     int)
        _opt_num("--camera-port",     "camera_port",     int)
        _opt_str("--capture-file",    "capture_file")
        _opt_num("--capture-frames",  "capture_frames",  int)
        _opt_num("--inject-delay",    "inject_delay",    float)
        _opt_num("--inject-fps",      "inject_fps",      float)
        _opt_str("--inject-ssrc",     "inject_ssrc")       # proxy parses hex-or-dec
        _opt_flag("--inject-only",    "inject_only")
        _opt_num("--rtcp-sr-interval","rtcp_sr_interval", float)
        _opt_str("--tcpkill-iface",   "tcpkill_iface")
        _opt_num("--tcpkill-delay",   "tcpkill_delay",   float)

        level = str(args.get("log_level", "")).strip().lower()
        if level:
            if level not in self._LOG_LEVELS:
                raise ValueError(f"log_level must be one of {sorted(self._LOG_LEVELS)}")
            argv += ["--log-level", level]

        return argv


# ---------- HTTP server ----------

class _ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(controller: ProxyController):
    class Handler(http.server.BaseHTTPRequestHandler):
        # Reroute http.server's noisy default logging into our logger.
        def log_message(self, fmt: str, *args) -> None:  # noqa: A002, ARG002
            log.debug("http %s - %s", self.address_string(), fmt % args)

        # ---- routes ----

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._serve_static("index.html", "text/html; charset=utf-8")
                return
            if self.path == "/api/status":
                self._json(200, controller.status())
                return
            if self.path == "/api/logs":
                self._serve_logs()
                return
            self.send_error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/start":
                try:
                    body = self._read_json()
                    status = controller.start(body)
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                    return
                except FileNotFoundError as e:
                    self._json(500, {"error": f"proxy binary not found: {e}"})
                    return
                except OSError as e:
                    self._json(500, {"error": f"spawn failed: {e}"})
                    return
                self._json(200, status)
                return
            if self.path == "/api/stop":
                self._json(200, controller.stop())
                return
            self.send_error(404, "not found")

        # ---- helpers ----

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("invalid request body")
            raw = self.rfile.read(length)
            try:
                obj = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError(f"invalid JSON: {e}") from None
            if not isinstance(obj, dict):
                raise ValueError("body must be a JSON object")
            return obj

        def _json(self, code: int, obj: dict) -> None:
            payload = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

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

        def _serve_logs(self) -> None:
            # NDJSON over HTTP chunked. One log entry per line as a JSON object.
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

            q = controller.subscribe()
            try:
                while True:
                    try:
                        entry = q.get(timeout=1.0)
                    except Empty:
                        # Idle keepalive — a comment line keeps NAT/proxies open
                        # without appearing in the parsed stream (newline-only).
                        if not self._send_chunk(b"\n"):
                            break
                        continue
                    payload = (json.dumps(entry, separators=(",", ":")) + "\n").encode("utf-8")
                    if not self._send_chunk(payload):
                        break
            finally:
                controller.unsubscribe(q)
                try:
                    self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        def _send_chunk(self, data: bytes) -> bool:
            try:
                self.wfile.write(f"{len(data):x}\r\n".encode("ascii"))
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

    return Handler


# ---------- Main ----------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Localhost web GUI to drive the rtspoofing proxy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The dashboard launches rtspoofing subprocesses with the arguments\n"
            "sent by the browser. Keep --host loopback-only in untrusted LANs:\n"
            "exposing this on 0.0.0.0 lets any machine on the network pick the\n"
            "args and spawn the proxy under your account.\n"
        ),
    )
    ap.add_argument("--proxy-binary", default="../RE/target/release/rtspoofing",
                    help="path to the rtspoofing binary (default: ../RE/target/release/rtspoofing)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host for the dashboard (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8090,
                    help="dashboard HTTP port (default: 8090)")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    binary = Path(args.proxy_binary).expanduser().resolve()
    if not binary.exists():
        log.error("proxy binary not found at %s — build it first (cd RE && cargo build --release)", binary)
        return 1
    if not os.access(binary, os.X_OK):
        log.error("proxy binary at %s is not executable", binary)
        return 1

    controller = ProxyController(binary)
    handler_cls = _make_handler(controller)

    try:
        server = _ThreadingHTTPServer((args.host, args.port), handler_cls)
    except OSError as e:
        log.error("cannot bind %s:%d: %s", args.host, args.port, e)
        return 1

    log.info("dashboard at http://%s:%d/   (proxy=%s)", args.host, args.port, binary)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Ctrl-C — shutting down")
    finally:
        controller.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
