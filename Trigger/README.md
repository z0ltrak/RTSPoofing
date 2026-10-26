# Trigger — CLI + ESP32 button for the live demo

Tiny command-line tool that flips the RTSPoofing proxy on and off from
one place, plus a serial bridge and an ESP32 sketch so a bystander at
a congress can press a button and watch the camera feed change.

```
   ┌─ ESP32 panel ──┐   USB-serial   ┌─ trigger-serial.sh ─┐    exec    ┌─ rtspoof-ctl ──────┐
   │ GPIO32 "attack"  ───────────▶   │  reads /dev/ttyACM0 │  ───────▶  │ arpspoof on + spoof│
   │ GPIO33 "reset"   ───────────▶   │  CMD_MAP: word →    │  ───────▶  │ panic (all off)    │
   │ GPIO25 "spoof"   ───────────▶   │  rtspoof-ctl argv   │  ───────▶  │ spawn inject proxy │
   │ GPIO26 "normal"  ───────────▶   │                     │  ───────▶  │ kill proxy         │
   │ GPIO27 "arpspoof"───────────▶   │                     │  ───────▶  │ arpspoof on        │
   │ GPIO14 "status"  ───────────▶   │                     │  ───────▶  │ report state       │
   └────────────────┘                └─────────────────────┘            └────────────────────┘
```

Each ESP32 button prints one **command word**; the bridge's `CMD_MAP`
table correlates that word to an `rtspoof-ctl` subcommand. Add a button
by adding a row to `esp32/button.ino`'s `BUTTONS[]` table and a matching
key to `CMD_MAP` — those two tables are the whole contract.

The CLI is deliberately boring. One subcommand per action, PID files in
`/tmp`, a config file next to it. Each call is a one-shot: no daemon,
no web UI, nothing to leave running between presses.

## Pieces

| File | What it is |
|---|---|
| `rtspoof-ctl`        | Python CLI. Subcommands: `spoof`, `normal`, `toggle`, `arpspoof`, `attack`, `panic`, `status`, `logs`. |
| `config.example.ini` | Presaved proxy **and** arpspoof settings — copy to `config.ini` and edit. |
| `trigger-serial.sh`  | Zero-dependency bash watcher; reads words from a serial port and correlates each (via `CMD_MAP`) to a CLI subcommand. |
| `esp32/button.ino`   | Arduino sketch: a declarative `BUTTONS[]` table, one GPIO → one command word. |

### Command vocabulary

What the ESP32 can say, and what the host does with it. The ESP32's
`BUTTONS[]` table and the bridge's `CMD_MAP` are mirror images of this:

| Serial word (+ aliases)      | `rtspoof-ctl`     | Effect |
|---|---|---|
| `attack`, `go`               | `attack`          | ARP-poison the pair **and** start injecting (full MITM, one press). |
| `reset`, `panic`, `clear`    | `panic`           | Stop the proxy, stop arpspoof, restore `ip_forward`. Safe to spam. |
| `spoof`, `inject`, `s`       | `spoof`           | Start the inject proxy only. |
| `normal`, `stop`, `n`        | `normal`          | Stop the proxy only. |
| `toggle`, `t`                | `toggle`          | Flip the proxy between spoof/normal. |
| `arpspoof`, `arp`            | `arpspoof on`     | Start ARP poisoning only (no inject). |
| `unarp`, `noarp`             | `arpspoof off`    | Stop ARP poisoning, restore `ip_forward`. |
| `status`, `?`               | `status`          | Print proxy + arpspoof state (to the bridge's stdout). |

Words are matched case-insensitively and whitespace-trimmed. Anything
not in the table is logged and ignored, and so are lines beginning with
`#` (the ESP32's boot banner).

## Setup

### 1. Build the proxy (once)

```bash
cd RE
cargo build --release
```

### 2. Record a `.rtp` to replay

The spoof needs a capture file. Do a one-off recording with the proxy
directly (not via `rtspoof-ctl` — that's for the inject state only):

```bash
sudo ./RE/target/release/rtspoofing \
    --mode record \
    --camera-host 192.168.1.108 \
    --capture-file captured.rtp
# let it run for ~10s, then Ctrl-C.
```

### 3. Configure the CLI

```bash
cd Trigger
cp config.example.ini config.ini
$EDITOR config.ini          # set camera_host, listen_port, capture_file
chmod +x rtspoof-ctl trigger-serial.sh
```

### 4. Smoke-test from the shell

```bash
sudo ./rtspoof-ctl status      # → proxy: normal / arpspoof: off
sudo ./rtspoof-ctl spoof       # → spoofing · pid=... · log=/tmp/rtspoof-ctl.log
sudo ./rtspoof-ctl status      # → proxy: spoofing · pid=... · up 2s
sudo ./rtspoof-ctl logs -f     # watch what the proxy is doing
sudo ./rtspoof-ctl normal      # → stopped (pid=...)
```

`sudo` because the proxy binds port 554 and the ARP side rewrites
`ip_forward` and sends raw frames. If you've `setcap`'d the proxy binary
you can run *it* as yourself; arpspoof still needs root. The pid files in
`/tmp` work for either.

### 5. ARP spoofing — now driven by the CLI

The proxy only intercepts what already lands on this host. For the full
NVR→camera MITM you need `arpspoof` poisoning both victims. That used to
be a manual pair of commands; `rtspoof-ctl` now owns it, so the ESP32 can
trigger it too. Fill in the `[arpspoof]` section of `config.ini`
(`iface`, `nvr_ip`, `camera_ip`), then:

```bash
sudo ./rtspoof-ctl arpspoof on   # enables ip_forward + poisons both ways
sudo ./rtspoof-ctl status        # → arpspoof: on · pids=...,...
sudo ./rtspoof-ctl arpspoof off  # kills both, restores ip_forward as found
```

`arpspoof on` enables `ip_forward` (remembering its prior value),
launches the two `arpspoof -t` processes, and tracks both PIDs. `off`
(and `panic`) SIGTERM them — so arpspoof re-ARPs the victims back to
their real MACs — then puts `ip_forward` back exactly as it was.

For a one-press full attack, use `attack` (arpspoof on **then** spoof)
and `panic`/`reset` to tear it all down:

```bash
sudo ./rtspoof-ctl attack        # arpspoof on + inject proxy
sudo ./rtspoof-ctl panic         # proxy off + arpspoof off + ip_forward restored
```

## The ESP32 side

### ESP32-C3 display button (`esp32_hacking_button`)

Upload `esp32_hacking_button/arduino/HackingButton/HackingButton.ino` with its
existing ESP32-C3 / TFT_eSPI settings and GPIO6-to-GPIO7 button wiring. After
the proxy, capture and `config.ini` setup above, close Arduino Serial Monitor
and run this bridge on the Linux RTSPoofing host:

```bash
cd Trigger
sudo ./trigger-serial.sh /dev/ttyACM0 115200
```

Each accepted press sends `ANIMATION_START`, mapped to `rtspoof-ctl attack`.
When the display returns to READY, it sends `ANIMATION_END`, mapped to
`rtspoof-ctl panic`: stop injection and ARP spoofing and restore `ip_forward`.
Injection is requested for the **whole 14.5-second animation**, starting at
the press, including the simulated preparation phases. There is no separate
host timer to keep in sync. Held or busy presses do not extend the demo.
The bridge also tears down an active demo on Ctrl-C, termination or serial EOF
(for example, USB unplug), and rolls back a failed start.

Normal operation requires the viewer to connect to the camera's address,
with the existing lab routing configured to reach the proxy during the demo.
Proxy startup, ARP restoration and viewer reconnection add latency; the serial
events control when injection starts/stops, not exact video display timing.
Use this bridge alone on the port; the Arduino project's Python listener is
an optional standalone callback example and does not control RTSPoofing.

The six-button sketch below remains available at its original 9600 baud.

### Wiring

One momentary pushbutton per command word, each to ground — no external
resistors (the sketch enables internal pull-ups). The default
`BUTTONS[]` table in `esp32/button.ino` wires six:

```
    GPIO 32 ──[ button ]── GND          // "attack"
    GPIO 33 ──[ button ]── GND          // "reset"
    GPIO 25 ──[ button ]── GND          // "spoof"
    GPIO 26 ──[ button ]── GND          // "normal"
    GPIO 27 ──[ button ]── GND          // "arpspoof"
    GPIO 14 ──[ button ]── GND          // "status"
```

Wire only the buttons you want — delete the rows you don't from
`BUTTONS[]` (and the matching keys from `CMD_MAP` in `trigger-serial.sh`
if you want the host to reject them). To add one, append a
`{ <pin>, "<word>", HIGH, 0 }` row; use pull-up-capable pins (avoid
input-only GPIO 34–39 and the boot-strapping pins 0/2/15).

Any ESP32 dev board with USB-serial works. If yours uses a CP2102 or
CH340 bridge, your port will be `/dev/ttyUSB0` instead of
`/dev/ttyACM0` — pass the right one to the serial bridge.

### Flash the sketch

Open `esp32/button.ino` in the Arduino IDE (or `arduino-cli`), pick
your ESP32 board, and upload. The sketch sends one lowercase word per
press over the USB-serial at 9600 bps.

### Run the bridge on the host

```bash
cd Trigger
sudo ./trigger-serial.sh /dev/ttyACM0 9600
```

That's it. The bridge sits in the foreground, prints each dispatched
command, and exits cleanly on Ctrl-C. If you want it to survive
logout, drop it into a systemd unit — or just `tmux`.

### Testing the bridge without an ESP32

If the hardware hasn't arrived yet, `socat` can hand you a pair of
virtual serial ports — one for the bridge to listen on, one for you
to type into (simulating button presses):

```bash
# terminal A — make a virtual pty pair
socat -d -d pty,raw,echo=0 pty,raw,echo=0
# prints two paths, e.g.:
#   PTY is /dev/pts/5
#   PTY is /dev/pts/6
# leave this running

# terminal B — point the bridge at one end
sudo ./trigger-serial.sh /dev/pts/5 9600

# terminal C — pretend to be the ESP32 pressing buttons
printf 'attack\n'   > /dev/pts/6
printf 'status\n'   > /dev/pts/6
printf 'reset\n'    > /dev/pts/6
printf 'arpspoof\n' > /dev/pts/6
printf 'bogus\n'    > /dev/pts/6   # → "ignoring unknown command"
```

Each `printf` lands as one "button press" and the bridge prints
`> attack → rtspoof-ctl attack` (etc.) as it dispatches, mirroring every
word in `CMD_MAP`. When the real ESP32 shows up, replace `/dev/pts/5`
with `/dev/ttyACM0` and the rest is identical — the sketch sends those
exact lines.

### One- or two-button variant

If the panel only has room for one button, trim `BUTTONS[]` to a single
row and give it the word you want — `{ 32, "toggle", HIGH, 0 }` to flip
the proxy on every press, or `{ 32, "attack", HIGH, 0 }` paired with a
second `{ 33, "reset", HIGH, 0 }` for a classic "on / off" pair that
drives the full MITM. The host needs no changes: every default word is
already in `CMD_MAP`.

## Why not just a hotkey?

A keybinding depends on the laptop running `trigger-serial.sh`'s
desktop having focus on the right window. The USB-serial path works
without a window manager at all, which is the whole point for a kiosk
demo.

## Troubleshooting

- `rtspoof-ctl spoof` says the proxy exited immediately — look at
  `/tmp/rtspoof-ctl.log`; usually it's "port already bound" (another
  proxy is still running) or "capture file not found".
- `rtspoof-ctl status` says "normal" after a kill -9 — the stale
  pid file gets cleared automatically on the next call. Just run
  `spoof` again.
- `trigger-serial.sh` reports "serial device not found" — unplug and
  replug the ESP32, then `ls /dev/ttyACM* /dev/ttyUSB*` to find its
  new path and pass it as the first argument.
- Nothing happens when you press the button but the serial device is
  there — add a `cat` test: `sudo cat /dev/ttyACM0` and press the
  button. You should see the boot banner (`# ready`, `# GPIO 32 ->
  attack`, …) and one word per press. If not, re-flash the sketch
  (the ESP32 occasionally boots into bootloader mode).
- A press prints `ignoring unknown command` — the word the ESP32 sent
  isn't a key in `CMD_MAP`. The two tables have drifted: make the
  sketch's `BUTTONS[]` word match a `CMD_MAP` key in `trigger-serial.sh`.
- `arpspoof on` exits immediately — check `[arpspoof]` `iface`/`nvr_ip`/
  `camera_ip`, that you're root, and `/tmp/rtspoof-ctl.log`. `ip_forward`
  is auto-restored on the failure.
