# Dashboard — localhost GUI for the rtspoofing proxy

Small Python-only web dashboard that drives the Rust proxy
(`RE/target/release/rtspoofing`) over a browser instead of a terminal.
Built for the live demo: switch modes, start/stop, watch the log tail,
all without alt-tabbing to a shell.

```
Browser ──HTTP:8090──► Dashboard (python) ──spawn──► rtspoofing (RE/)
                              │
                              └──NDJSON over chunked HTTP──► Browser log pane
```

## Scope

- One proxy process at a time per dashboard. Starting a new one stops
  the running one first, so you always end with exactly one (or none,
  if it crashed on launch).
- Record / inject modes with every proxy flag exposed in the UI
  (listen bind/port, camera host/port, capture file, inject tunables,
  tcpkill, log level).
- Live `stdout`+`stderr` tail, auto-scrolling with a filter and clear.
- Status chip (running / stopped / exited N) with pid and uptime.

## Non-goals

- Not a session controller for an already-running proxy. The proxy
  itself has no runtime command interface; the dashboard owns the
  process lifecycle instead.
- Not authentication. Default bind is `127.0.0.1` only. Putting the
  dashboard on `0.0.0.0` hands anyone on the LAN a form that spawns
  arbitrary `rtspoofing` arguments under your account — don't do it
  on an untrusted network.

## Usage

Build the proxy first (one time):

```bash
cd RE
cargo build --release
```

Then from the repo root (or anywhere, with `--proxy-binary` pointed at
the binary):

```bash
python3 Dashboard/dashboard.py \
  --proxy-binary RE/target/release/rtspoofing
```

Open <http://127.0.0.1:8090/> and drive the proxy from there.

### Flags

```
--proxy-binary PATH   path to the rtspoofing binary
                      (default: ../RE/target/release/rtspoofing)
--host HOST           bind host for the dashboard (default: 127.0.0.1)
--port PORT           dashboard HTTP port         (default: 8090)
--log-level LEVEL     dashboard's own log level   (default: INFO)
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

## What's inside

- `dashboard.py` — stdlib-only Python server (~400 lines). Owns the
  proxy subprocess, serves the SPA, fans the proxy's stderr/stdout
  out to all connected browser clients as NDJSON over HTTP chunked
  (same transport pattern as `NVR/web_server.py`).
- `web/index.html` — single-file SPA, inline CSS/JS, no external
  dependencies. Mode-conditional form, live log pane, toast
  notifications.
