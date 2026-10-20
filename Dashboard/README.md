# Dashboard — localhost GUI for the RTSPoofing MITM

Small Python-only web dashboard that drives the full MITM setup from a
browser: the two `arpspoof` legs that put the attacker between NVR and
camera, and the Rust proxy
(`RE/target/release/rtspoofing`) that does the actual recording and
injection. Built for the live demo: start/stop everything, watch a
combined log tail, no alt-tabbing to a shell.

```
            ┌───────────── Browser (http://127.0.0.1:8090/) ─────────────┐
            │  Targets │ ARP Spoof │ Proxy  │   combined log pane         │
            └──────┬──────────┬────────┬────────────┬──────────────────────┘
                   │ POST     │ POST   │ POST       │ GET /api/logs (chunked NDJSON)
                   ▼          ▼        ▼            │
            ┌──────────────── dashboard.py ─────────┼─────────────────────┐
            │   ProxyController   │  ArpspoofController   │  LogBus       │
            │        │                      │                   ▲          │
            │   spawn/kill             spawn/kill       stdout+stderr      │
            │        ▼                      ▼                   │          │
            │   rtspoofing (RE/)      arpspoof × {1,2}──────────┘          │
            └───────────────────────────────────────────────────────────────┘
```

## Scope

- One proxy process and up to two `arpspoof` processes per dashboard.
  Starting a new one of either kind stops the previous ones first, so
  you always end with exactly the set you asked for (or none, if
  something crashed on launch).
- Record / inject modes for the proxy with every CLI flag exposed in
  the UI (listen bind/port, camera host/port, capture file, inject
  tunables, tcpkill, log level).
- `arpspoof` legs: **Both** (standard NVR↔camera MITM), **Poison NVR**,
  **Poison camera**. Shared Targets fields feed both panels and the
  proxy's `--camera-host`.
- Live combined `stdout`+`stderr` tail, colour-tagged per source
  (`proxy-out` / `proxy-err` / `arp-nvr` / `arp-cam` / `dash`), with a
  text filter, source toggles and auto-scroll.
- Dual status chips (ARP running legs · proxy pid/uptime).
- Form values auto-save to `localStorage`, so a reload comes back
  pre-filled.
- Keyboard shortcuts: <kbd>Ctrl</kbd>+<kbd>Enter</kbd> launches the
  whole MITM (ARP + proxy), <kbd>Ctrl</kbd>+<kbd>.</kbd> stops
  everything.

## Non-goals

- Not a session controller for an already-running proxy. The proxy
  itself has no runtime command interface; the dashboard owns the
  process lifecycle instead.
- Not authentication. Default bind is `127.0.0.1` only. Putting the
  dashboard on `0.0.0.0` hands anyone on the LAN a form that spawns
  arbitrary `rtspoofing` and `arpspoof` arguments under your account
  — don't do it on an untrusted network.

## Usage

Build the proxy first (one time):

```bash
cd RE
cargo build --release
```

Install `arpspoof` (one time, Debian/Ubuntu):

```bash
sudo apt install dsniff
```

Then from the repo root (or anywhere, with `--proxy-binary` pointed at
the binary):

```bash
# ARP spoofing needs raw sockets, so most people run the dashboard
# itself as root; stay on 127.0.0.1 and it's the standard lab setup.
sudo python3 Dashboard/dashboard.py \
  --proxy-binary RE/target/release/rtspoofing
```

Open <http://127.0.0.1:8090/> and drive everything from there.

For a full MITM, don't forget to enable IPv4 forwarding so traffic
between NVR and camera actually relays through the attacker host:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```

The ARP panel surfaces this reminder inline.

### Flags

```
--proxy-binary PATH      path to the rtspoofing binary
                         (default: ../RE/target/release/rtspoofing)
--arpspoof-binary PATH   arpspoof binary or absolute path
                         (default: arpspoof — resolved via PATH)
--host HOST              bind host for the dashboard (default: 127.0.0.1)
--port PORT              dashboard HTTP port         (default: 8090)
--log-level LEVEL        dashboard's own log level   (default: INFO)
```

### Needing port 554

The proxy's `--listen-port` defaults to 554, which requires root. Two
options for the lab:

```bash
# option A: give the binary CAP_NET_BIND_SERVICE once, run as yourself
sudo setcap 'cap_net_bind_service=+ep' RE/target/release/rtspoofing

# option B: just pick a high port (change in the dashboard form)
#   e.g. 5540, then point the NVR at rtsp://attacker:5540/stream
```

If you're running the whole dashboard as root for `arpspoof` anyway,
you don't need either — the proxy inherits the privilege.

### Avoiding root for arpspoof

If you'd rather not run the dashboard as root, you can give `arpspoof`
the raw-socket capability once and run everything as your user:

```bash
sudo setcap cap_net_raw+ep "$(command -v arpspoof)"
```

## API, if you want to script it

The dashboard also exposes a tiny JSON API that the SPA uses:

```
GET  /api/status          → { proxy: {...}, arp: {...} }
POST /api/start           → { … proxy status … }    body: proxy config
POST /api/stop            → { … proxy status … }
POST /api/arp/start       → { … arp status … }      body: {iface, nvr_ip, cam_ip, direction}
POST /api/arp/stop        → { … arp status … }
POST /api/stop_all        → { proxy, arp }          stops both
GET  /api/logs            → chunked NDJSON stream   one JSON entry per line
```

## What's inside

- `dashboard.py` — stdlib-only Python server (~500 lines). Owns the
  proxy and arpspoof subprocesses, serves the SPA, fans every stderr
  and stdout line out to all connected browser clients as NDJSON over
  HTTP chunked (same transport pattern as `NVR/web_server.py`).
- `web/index.html` — single-file SPA, inline CSS/JS, no external
  dependencies. Shared Targets section, ARP + proxy panels, dual
  status chips, combined log pane, toast notifications, localStorage
  persistence.
