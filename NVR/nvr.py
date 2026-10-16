#!/usr/bin/env python3
"""
RTSPoofing NVR — minimal RTSP viewer/recorder for the PoC lab.

This is the "viewer side" of the attack chain the RTSPoofing proxy targets.
It connects to an RTSP IP camera (directly or through the proxy, depending on
your lab's routing), negotiates TCP-interleaved transport — the exact path the
proxy intercepts — then:

  * depacketizes RTP into an H.264 / H.265 Annex-B elementary stream,
  * pipes it to `ffplay` for live display (toggle with --no-display),
  * optionally records to MP4 via `ffmpeg -c copy`,
  * optionally writes a `.rtp` capture in the proxy's own binary format, so
    its output is directly loop-injectable with `rtspoofing --mode inject`.

A one-line live status is printed to stderr so a running demo makes the
on-wire state visible: frames received, SSRC, RTP timestamp, wall-clock
drift between captures and now, and keyframe cadence.

The RTSPoofing paper and talk live in the sibling `paper/` and `RTSPoofingTalk/`
directories; the recorder exists mainly so a demo can show the end-to-end
chain (camera → ARP/MITM → NVR) without pulling in a full VMS.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rtp_depay import RtpDepayH264, RtpDepayH265, parse_rtp  # noqa: E402
from rtsp_client import RtspClient, RtspError, iter_interleaved  # noqa: E402
from web_server import NvrWebServer  # noqa: E402


log = logging.getLogger("nvr")

# Signalled by SIGINT/SIGTERM; distinguishes "user wants out" from "stream died"
# so the reconnect loop can tell those two cases apart.
_user_stop = threading.Event()


# ---------- The .rtp capture file writer (same format as PE/ and RE/) ----------

class RtpCaptureWriter:
    """
    Writes the proxy's `.rtp` capture format:

        [4B total_len big-endian]
        [1B channel][1B reserved=0]
        [2B rtp_len big-endian]
        [rtp_len bytes of RTP payload]

    where total_len = 4 + rtp_len. The format is already parsed by
    PE/RTSPoofing.py::read_capture_file and RE/src/capture.rs, so a
    file produced here can feed `rtspoofing --mode inject` without
    any conversion.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = open(path, "ab", buffering=1 << 16)
        self._lock = threading.Lock()
        self._count = 0

    @property
    def frames(self) -> int:
        return self._count

    def write(self, channel: int, rtp_payload: bytes) -> None:
        rtp_len = len(rtp_payload)
        total_len = 1 + 1 + 2 + rtp_len
        header = struct.pack("!IBBH", total_len, channel & 0xFF, 0, rtp_len)
        with self._lock:
            self._fh.write(header)
            self._fh.write(rtp_payload)
            self._count += 1

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass


# ---------- Sinks that consume the depacketized Annex-B stream ----------

class _SubprocessSink:
    """A tiny wrapper around a subprocess that owns an elementary-stream stdin."""

    def __init__(self, name: str, argv: list[str]) -> None:
        self.name = name
        self._argv = argv
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._broken = False

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("spawned %s: %s", self.name, " ".join(self._argv))
        except FileNotFoundError:
            log.error("%s not found on PATH; skipping sink %s", self._argv[0], self.name)
            self._broken = True

    def write(self, data: bytes) -> None:
        if self._broken or self._proc is None or self._proc.stdin is None:
            return
        with self._lock:
            try:
                self._proc.stdin.write(data)
            except (BrokenPipeError, OSError):
                # The viewer or recorder died — mark the sink dead and keep
                # the rest of the NVR running. A broken ffplay in --no-display
                # terrain is normal (viewer closed); a broken ffmpeg means
                # the recording is cut off, which we log but don't crash on.
                self._broken = True
                log.warning("%s pipe broken — sink disabled", self.name)

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _player_argv(codec: str, title: str) -> list[str]:
    fmt = "hevc" if codec in ("H265", "HEVC") else "h264"
    return [
        "ffplay",
        "-hide_banner",
        "-loglevel", "error",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-framedrop",
        "-f", fmt,
        "-window_title", title,
        "-i", "-",
    ]


def _recorder_argv(codec: str, out_path: Path) -> list[str]:
    fmt = "hevc" if codec in ("H265", "HEVC") else "h264"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-fflags", "+genpts",
        "-f", fmt,
        "-i", "-",
        "-c", "copy",
        "-movflags", "+faststart+frag_keyframe+empty_moov",
        "-y",
        str(out_path),
    ]


# ---------- Live stats ----------

@dataclass
class LiveStats:
    rtp_packets: int = 0
    nalus: int = 0
    keyframes: int = 0
    bytes_in: int = 0
    first_wallclock: float = 0.0
    last_rtp_ts: int = 0
    first_rtp_ts: int = 0
    ssrc: int = 0
    last_print: float = 0.0

    def snapshot(self) -> Optional[dict]:
        """Compute a stats dict suitable for publishing to the viewer, or None
        if we haven't seen the first packet yet."""
        if self.first_wallclock == 0.0:
            return None
        elapsed = max(1e-6, time.time() - self.first_wallclock)
        rtp_elapsed = ((self.last_rtp_ts - self.first_rtp_ts) & 0xFFFFFFFF) / 90000.0
        return {
            "ssrc": f"0x{self.ssrc:08x}",
            "rtp_packets": self.rtp_packets,
            "nalus": self.nalus,
            "keyframes": self.keyframes,
            "wall_s": round(elapsed, 2),
            "media_clock_s": round(rtp_elapsed, 2),
            "drift": round(rtp_elapsed - elapsed, 3),
            "kbps": round((self.bytes_in * 8) / 1000 / elapsed, 1),
            "fps": round(self.rtp_packets / elapsed, 2),
            "state": "streaming",
        }

    def tick(self, interval: float = 1.0) -> Optional[str]:
        now = time.monotonic()
        if now - self.last_print < interval:
            return None
        self.last_print = now
        snap = self.snapshot()
        if snap is None:
            return None
        return (
            f"ssrc={snap['ssrc']}  "
            f"rtp={snap['rtp_packets']:>6}  "
            f"nalus={snap['nalus']:>6}  "
            f"keyframes={snap['keyframes']:>3}  "
            f"wall={snap['wall_s']:7.1f}s  "
            f"media_clock={snap['media_clock_s']:7.1f}s  "
            f"drift={snap['drift']:+6.2f}s  "
            f"bitrate={snap['kbps']:7.0f}kbps  "
            f"rate={snap['fps']:5.1f}pkt/s"
        )


# ---------- The main loop ----------

def _rotate_path(base: Optional[str], attempt: int) -> Optional[str]:
    """
    Return the output path for a given attempt.

    - Attempt 1 keeps the exact filename the user specified, so a non-reconnect
      session produces exactly `session.mp4`, not `session.001.mp4`.
    - Attempts 2+ insert a zero-padded index before the extension:
      `session.mp4` -> `session.002.mp4`, `loopable.rtp` -> `loopable.002.rtp`.
    """
    if not base:
        return None
    if attempt <= 1:
        return base
    p = Path(base)
    return str(p.with_name(f"{p.stem}.{attempt:03d}{p.suffix}"))


def run_once(
    args: argparse.Namespace,
    attempt: int,
    web: Optional[NvrWebServer] = None,
) -> str:
    """
    One connect/play/stream cycle. Returns one of:
      - "ok"      — the stream ran and the user asked to stop; no retry.
      - "retry"   — transient failure (timeout, reset, stall); retry allowed.
      - "fatal"   — permanent failure (auth, SDP) that would just repeat.
    """
    client = RtspClient(args.url, user_agent=args.user_agent)
    sinks: list[_SubprocessSink] = []
    rtp_capture: Optional[RtpCaptureWriter] = None
    verdict = "retry"  # pessimistic default; overwritten on clean exit

    # Access-unit accumulator for the web viewer. Hoisted to the top of
    # the function so the `finally` block can safely call _flush_au() even
    # on an early-return error path (connect timeout, auth failure, …)
    # where the main for-loop never ran.
    au_buf: list[bytes] = []
    au_is_key = False
    au_ts: Optional[int] = None

    def _flush_au() -> None:
        nonlocal au_buf, au_is_key, au_ts
        if web is not None and au_buf:
            web.publish_video(b"".join(au_buf), au_is_key)
        au_buf = []
        au_is_key = False
        au_ts = None

    def _web_state(state: str, detail: str = "") -> None:
        if web is not None:
            web.publish_status({"state": state, "detail": detail, "attempt": attempt})

    _web_state("connecting", f"RTSP attempt #{attempt}")

    try:
        log.info("[attempt %d] connecting to %s", attempt, args.url.rsplit("@", 1)[-1])
        try:
            client.connect()
            client.options()
            track = client.describe()
        except OSError as e:
            # TimeoutError, ConnectionRefusedError, ConnectionResetError, no route, …
            # These are precisely the arpspoof-side failures: SYN black-holed by an
            # attacker with ip_forward=0, iptables REDIRECT pointing at a port with
            # nothing listening, etc. Retriable.
            log.error("transport error on connect: %s", e)
            _web_state("reconnecting", f"transport: {e}")
            return "retry"
        except RtspError as e:
            # 401 after we've already tried creds, SDP has no video track, …
            # Retrying won't help without user intervention.
            log.error("RTSP error on handshake: %s", e)
            _web_state("error", f"handshake: {e}")
            return "fatal"

        log.info(
            "video track: encoding=%s pt=%d clock=%d control=%s",
            track.encoding, track.payload_type, track.clock_rate, track.control,
        )
        try:
            client.setup(rtp_channel=0)
            log.info(
                "session=%s interleaved=%d-%d",
                client._session, track.rtp_channel, track.rtcp_channel,
            )
            client.play()
        except OSError as e:
            log.error("transport error during SETUP/PLAY: %s", e)
            _web_state("reconnecting", f"setup: {e}")
            return "retry"
        except RtspError as e:
            log.error("RTSP error during SETUP/PLAY: %s", e)
            _web_state("error", f"setup: {e}")
            return "fatal"

        # Publish the stream parameters to any connected browser. Each
        # publish_config bumps the server's epoch so the player calls
        # VideoDecoder.configure() again — necessary when the camera changes
        # SPS/PPS (resolution/bitrate change) or when a reconnect lands on a
        # fresh RTSP session with new parameter sets.
        if web is not None:
            web.publish_config(
                codec="H264" if track.encoding == "H264" else "H265",
                sps=list(track.sps),
                pps=list(track.pps),
                vps=list(track.vps),
            )

        # After PLAY, apply the stall timeout so a dead stream can't block
        # recv() forever — recv raises TimeoutError and we reconnect.
        if args.stall_timeout and args.stall_timeout > 0:
            client.sock.settimeout(args.stall_timeout)

        if track.encoding == "H264":
            depay = RtpDepayH264(sps_pps=[*track.sps, *track.pps])
        elif track.encoding in ("H265", "HEVC"):
            depay = RtpDepayH265(vps_sps_pps=[*track.vps, *track.sps, *track.pps])
        else:
            log.error("unsupported codec in SDP: %s", track.encoding)
            return "fatal"

        if not args.no_display:
            display = _SubprocessSink(
                "ffplay",
                _player_argv(track.encoding, f"RTSPoofing NVR — {client.host}"),
            )
            display.start()
            sinks.append(display)
        mp4_path = _rotate_path(args.record_mp4, attempt)
        if mp4_path:
            Path(mp4_path).parent.mkdir(parents=True, exist_ok=True)
            recorder = _SubprocessSink("ffmpeg", _recorder_argv(track.encoding, Path(mp4_path)))
            recorder.start()
            sinks.append(recorder)
        rtp_path = _rotate_path(args.record_rtp, attempt)
        if rtp_path:
            rtp_capture = RtpCaptureWriter(Path(rtp_path))
            log.info("writing .rtp capture to %s", rtp_path)

        # Prepend out-of-band parameter sets so the decoder can start immediately.
        prelude = depay.take_prelude()
        if prelude:
            for sink in sinks:
                sink.write(prelude)

        stats = LiveStats()
        last_web_status = 0.0

        try:
            for kind, channel, payload in iter_interleaved(client.sock, seed=client.consume_leftover()):
                if _user_stop.is_set():
                    verdict = "ok"
                    break
                if kind == "text":
                    log.debug("rtsp interleaved text (%d bytes)", len(payload))
                    continue

                if channel != track.rtp_channel:
                    if rtp_capture is not None:
                        rtp_capture.write(channel, payload)
                    continue

                parsed = parse_rtp(payload)
                if parsed is None:
                    continue

                stats.rtp_packets += 1
                stats.bytes_in += len(payload)
                if stats.first_wallclock == 0.0:
                    stats.first_wallclock = time.time()
                    stats.first_rtp_ts = parsed["ts"]
                    stats.ssrc = parsed["ssrc"]
                stats.last_rtp_ts = parsed["ts"]

                if rtp_capture is not None:
                    rtp_capture.write(channel, payload)

                # Timestamp change signals a new picture — flush any pending AU.
                if au_ts is not None and parsed["ts"] != au_ts:
                    _flush_au()

                for nalu in depay.feed(parsed["payload"], parsed["seq"]):
                    stats.nalus += 1
                    if track.encoding == "H264":
                        nal_type = nalu[4] & 0x1F
                        if nal_type == 5:
                            stats.keyframes += 1
                            au_is_key = True
                    else:
                        nal_type = (nalu[4] >> 1) & 0x3F
                        if nal_type in (19, 20, 21):
                            stats.keyframes += 1
                            au_is_key = True
                    for sink in sinks:
                        sink.write(nalu)
                    au_buf.append(nalu)

                au_ts = parsed["ts"]

                # RTP marker also closes the current access unit (end of frame),
                # for cameras that keep the same timestamp across multiple pics.
                if parsed["marker"]:
                    _flush_au()

                line = stats.tick()
                if line is not None:
                    sys.stderr.write("\r" + line)
                    sys.stderr.flush()
                    now = time.monotonic()
                    if web is not None and now - last_web_status >= 0.5:
                        snap = stats.snapshot()
                        if snap is not None:
                            web.publish_status(snap)
                        last_web_status = now
            else:
                # Generator exhausted without the user asking to stop → peer
                # closed the TCP connection. Retriable.
                log.warning("peer closed the RTSP connection")
        except TimeoutError:
            # Socket stall timeout fired — no RTP for stall_timeout seconds.
            # Classic symptom of ARP table re-poisoning, proxy restart, or
            # the camera itself hanging. Retriable.
            log.warning("stream stalled (no RTP for %.1fs)", args.stall_timeout)
        except (OSError, RtspError) as e:
            log.error("stream ended: %s", e)

    finally:
        # Flush any residual access unit so the viewer isn't missing the
        # last partial frame when a session ends cleanly.
        _flush_au()
        sys.stderr.write("\n")
        log.info("tearing down session")
        try:
            client.teardown()
        except Exception:
            pass
        client.close()
        for sink in sinks:
            sink.close()
        if rtp_capture is not None:
            log.info("wrote %d frames to %s", rtp_capture.frames, rtp_capture._path)
            rtp_capture.close()

    return verdict


def run(args: argparse.Namespace) -> int:
    """Reconnect loop around run_once. Returns a process exit code."""
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Only trap SIGTERM — leave SIGINT alone so Python's default
    # KeyboardInterrupt propagation makes Ctrl-C instantly abort any blocked
    # syscall (PEP 475 would otherwise retry the syscall silently).
    def _on_sigterm(signum, frame):  # noqa: ARG001
        log.info("SIGTERM — shutting down")
        _user_stop.set()

    signal.signal(signal.SIGTERM, _on_sigterm)

    # The web server (if asked for) lives for the whole process, not per
    # attempt — that's the whole point: the browser stays connected across
    # RTSP reconnects.
    web: Optional[NvrWebServer] = None
    if args.serve:
        host, port = _parse_serve(args.serve)
        try:
            web = NvrWebServer(host=host, port=port)
            web.start()
        except RuntimeError as e:
            log.error("web viewer disabled: %s", e)
            web = None

    attempt = 0
    try:
        while not _user_stop.is_set():
            attempt += 1
            verdict = run_once(args, attempt, web=web)

            if verdict == "ok" or _user_stop.is_set():
                if web is not None:
                    web.publish_status({"state": "stopped", "detail": "NVR exited"})
                return 0
            if verdict == "fatal":
                log.error("unrecoverable error — not reconnecting")
                if web is not None:
                    web.publish_status({"state": "error", "detail": "unrecoverable"})
                return 2
            if args.no_reconnect:
                log.error("--no-reconnect set — exiting after first failure")
                return 1
            if args.max_reconnects and attempt >= args.max_reconnects:
                log.error("max reconnects (%d) reached — giving up", args.max_reconnects)
                return 1

            delay = args.reconnect_delay
            log.info("reconnecting in %.1fs (next attempt: #%d)", delay, attempt + 1)
            if web is not None:
                web.publish_status({
                    "state": "reconnecting",
                    "detail": f"next attempt in {delay:.1f}s",
                    "attempt": attempt,
                })
            if _user_stop.wait(delay):
                return 0
    except KeyboardInterrupt:
        log.info("Ctrl-C — shutting down")
        return 0
    finally:
        if web is not None:
            web.stop()

    return 0


def _parse_serve(spec: str) -> tuple[str, int]:
    """Parse --serve values like '8080', ':8080', '127.0.0.1:8080', '0.0.0.0:8080'."""
    s = spec.strip()
    if s.startswith(":"):
        return "127.0.0.1", int(s[1:])
    if ":" in s:
        host, port = s.rsplit(":", 1)
        return host or "127.0.0.1", int(port)
    # Bare port
    return "127.0.0.1", int(s)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="RTSP IP-camera NVR for the RTSPoofing PoC lab.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Browser viewer at http://127.0.0.1:8080 — stays open across\n"
            "  # RTSP reconnects, decodes with WebCodecs, has live stats panel.\n"
            "  python nvr.py --url rtsp://admin:admin@192.168.1.108:554/stream \\\n"
            "                --no-display --serve 8080\n\n"
            "  # Classic ffplay window + continuous MP4 recording\n"
            "  python nvr.py --url rtsp://admin:admin@192.168.1.108:554/stream \\\n"
            "                --record-mp4 session.mp4\n\n"
            "  # Headless capture of a .rtp replay file for `rtspoofing --mode inject`\n"
            "  python nvr.py --url rtsp://admin:admin@192.168.1.108:554/stream \\\n"
            "                --no-display --record-rtp loopable.rtp\n"
        ),
    )
    ap.add_argument("--url", required=True,
                    help="rtsp://[user[:pass]@]host[:port]/path")
    ap.add_argument("--serve", default=None,
                    help="run a localhost web viewer on this port (e.g. 8080, ':8080', or 'host:port'). "
                         "The browser connection survives RTSP reconnects.")
    ap.add_argument("--no-display", action="store_true",
                    help="skip ffplay; useful for headless capture or when --serve is the viewer")
    ap.add_argument("--record-mp4", default=None,
                    help="write an MP4 of the stream (uses ffmpeg -c copy)")
    ap.add_argument("--record-rtp", default=None,
                    help="dump the RTP payloads in the proxy's .rtp format, re-injectable with rtspoofing --mode inject")
    ap.add_argument("--user-agent", default="RTSPoofing-NVR/0.1",
                    help="RTSP User-Agent string")
    ap.add_argument("--reconnect-delay", type=float, default=2.0,
                    help="seconds to wait before reconnecting after a failed/dropped stream (default: 2)")
    ap.add_argument("--max-reconnects", type=int, default=0,
                    help="give up after N failed attempts (0 = retry forever, default)")
    ap.add_argument("--stall-timeout", type=float, default=10.0,
                    help="treat the stream as dead and reconnect if no RTP arrives for this many seconds (0 to disable, default: 10)")
    ap.add_argument("--no-reconnect", action="store_true",
                    help="exit on first failure instead of retrying (equivalent to --max-reconnects 1)")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
