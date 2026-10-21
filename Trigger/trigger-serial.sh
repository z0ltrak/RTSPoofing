#!/usr/bin/env bash
# trigger-serial.sh — watches a serial port for one-word commands from an
# ESP32 button rig and dispatches `rtspoof-ctl` subcommands.
#
# The ESP32 sketch (see Trigger/esp32/button.ino) prints one of:
#
#     spoof   or  s         → rtspoof-ctl spoof
#     normal  or  n         → rtspoof-ctl normal
#     toggle  or  t         → rtspoof-ctl toggle
#
# Zero deps — just bash and stty. Lines starting with `#` are logged
# but ignored, so the ESP32 can send `# ready` on boot without
# triggering anything.
#
# Usage: ./trigger-serial.sh [port] [baud]
# Defaults: /dev/ttyACM0 @ 9600 bps.

set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
BAUD="${2:-9600}"
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CTL="$HERE/rtspoof-ctl"

if [ ! -c "$PORT" ]; then
  echo "trigger-serial: serial device not found: $PORT" >&2
  echo "               plug in the ESP32, or pass a different path:" >&2
  echo "               $0 /dev/ttyUSB0" >&2
  exit 1
fi

if [ ! -x "$CTL" ]; then
  echo "trigger-serial: rtspoof-ctl not executable at $CTL" >&2
  echo "               run:  chmod +x $CTL" >&2
  exit 1
fi

# Raw mode: fixed baud, no echo, no canonical processing, no CR/LF munging,
# no signal interception (so the ESP32's text doesn't fire SIGINT etc.).
stty -F "$PORT" "$BAUD" raw -echo -icrnl -onlcr -isig -ixon

echo "trigger-serial: watching $PORT @ ${BAUD}bps  →  $CTL"
echo "trigger-serial: ctrl-c to stop"

# Open the port once; the loop reads lines from fd 3 without re-opening.
exec 3< "$PORT"

while IFS= read -r line <&3; do
  cmd="$(printf '%s' "$line" | tr -d '\r\n\t ' | tr '[:upper:]' '[:lower:]')"
  case "$cmd" in
    "")        : ;;                                         # blank — noop
    \#*)       echo "serial: $cmd" ;;                        # comment — log only
    spoof|s)   echo "> spoof";   "$CTL" spoof   || true ;;
    normal|n)  echo "> normal";  "$CTL" normal  || true ;;
    toggle|t)  echo "> toggle";  "$CTL" toggle  || true ;;
    status|?)  echo "> status";  "$CTL" status  || true ;;
    *)         echo "serial: ignoring unknown command: $cmd" ;;
  esac
done
