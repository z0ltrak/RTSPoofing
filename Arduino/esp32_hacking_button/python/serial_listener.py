#!/usr/bin/env python3
"""Run on_animation_started() for each complete ANIMATION_START USB serial line."""
import argparse
import sys


EVENT = b"ANIMATION_START"


def on_animation_started():
    # Add your own Python code here.
    pass


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
