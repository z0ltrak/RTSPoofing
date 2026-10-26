#!/usr/bin/env bash
# trigger-serial.sh — reads one-word commands from an ESP32 over serial and
# correlates each to an `rtspoof-ctl` subcommand.
#
# The correlation lives in ONE place: the CMD_MAP table below. Each key is a
# word (or alias) the ESP32 can print; each value is the rtspoof-ctl argv it
# maps to. This table is the host-side mirror of the BUTTONS table in
# esp32/button.ino — keep the two in sync and the board and host agree on
# what every press means.
#
# Default vocabulary (see esp32/button.ino):
#
#     attack / go          → rtspoof-ctl attack        (arpspoof on + inject)
#     reset / panic / clear → rtspoof-ctl panic         (everything off)
#     spoof / inject / s    → rtspoof-ctl spoof         (inject proxy on)
#     normal / stop / n     → rtspoof-ctl normal        (proxy off)
#     toggle / t            → rtspoof-ctl toggle
#     arpspoof / arp        → rtspoof-ctl arpspoof on
#     unarp / noarp         → rtspoof-ctl arpspoof off
#     status / ?            → rtspoof-ctl status
#
# Zero deps — just bash and stty. Lines starting with '#' are logged but
# ignored, so the ESP32's "# ready" / "# GPIO 32 -> attack" banner is safe.
#
# Usage: ./trigger-serial.sh [port] [baud]
# Defaults: /dev/ttyACM0 @ 9600 bps.
# For esp32_hacking_button/HackingButton.ino, pass 115200 as the baud rate.
# ANIMATION_START / ANIMATION_END bracket the entire 14.5-second demo.

set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
BAUD="${2:-9600}"
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CTL="$HERE/rtspoof-ctl"

# ---- the correlation table -----------------------------------------------
# word (lowercased, trimmed)  →  rtspoof-ctl arguments
declare -A CMD_MAP=(
  [animation_start]="attack" [animation_end]="panic"
  [attack]="attack"       [go]="attack"
  [reset]="panic"         [panic]="panic"       [clear]="panic"
  [spoof]="spoof"         [inject]="spoof"      [s]="spoof"
  [normal]="normal"       [stop]="normal"       [n]="normal"
  [toggle]="toggle"       [t]="toggle"
  [arpspoof]="arpspoof on" [arp]="arpspoof on"
  [unarp]="arpspoof off"  [noarp]="arpspoof off"
  [status]="status"       [?]="status"
)

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
echo "trigger-serial: known words: ${!CMD_MAP[*]}"
echo "trigger-serial: ctrl-c to stop"

# Open the port once; the loop reads lines from fd 3 without re-opening.
exec 3< "$PORT"

# Only a demo started by this bridge needs automatic teardown on exit/unplug.
demo_active=0
stop_demo() {
  if (( demo_active )); then
    "$CTL" panic || return
    demo_active=0
  fi
}
trap stop_demo EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

while IFS= read -r line <&3; do
  # Normalise: strip CR/LF/tabs/spaces, lowercase.
  cmd="$(printf '%s' "$line" | tr -d '\r\n\t ' | tr '[:upper:]' '[:lower:]')"
  case "$cmd" in
    "")   : ;;                       # blank — noop
    \#*)  echo "serial: $cmd" ;;     # ESP32 diagnostic line — log only
    *)
      args="${CMD_MAP[$cmd]:-}"
      if [ -z "$args" ]; then
        echo "serial: ignoring unknown command: $cmd"
      else
        if [ "$cmd" = animation_start ]; then
          (( demo_active )) && continue  # Duplicate start must not restart it.
          demo_active=1
        elif [ "$cmd" = animation_end ] && (( ! demo_active )); then
          continue
        fi
        echo "> $cmd  →  rtspoof-ctl $args"
        # shellcheck disable=SC2086  # $args is a trusted, space-split argv
        if "$CTL" $args; then
          if [ "$args" = panic ]; then demo_active=0; fi
        elif [ "$cmd" = animation_start ]; then
          stop_demo || true  # Roll back a partially started demo.
        fi
      fi
      ;;
  esac
done
