# RTSPoofing

RTSP/TCP MITM proxy with RTP frame injection for recording and replaying RTSP streams.

![Rust](https://img.shields.io/badge/rust-2024-blue?logo=rust)
![Python](https://img.shields.io/badge/python-3.9%2B-yellow?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)

## Overview

**RTSPoofing** is a Man-in-the-Middle (MITM) tool for RTSP-over-TCP streams. It allows security researchers to:

- Record live RTP frames from an IP camera into a binary `.rtp` file.
- Inject previously recorded frames back into the stream, replacing or overlaying the live video.
- Perform ARP spoofing to transparently redirect traffic through the proxy.

This project was developed as a proof-of-concept for security research, demonstrating how video surveillance streams can be intercepted, recorded, and replayed without the NVR or viewer noticing.

> **Disclaimer**  
> This tool is intended strictly for research, educational purposes, and authorized security testing in controlled environments.

## Project Structure

```text
RTSPoofing/
├── PE/                    # Python prototype (first version)
│   ├── RTSPoofing.py      # Original MITM proxy
│   ├── rtp_probe.py       # RTP parameter detection
│   └── test_parser.py     # Debugging script
│
├── RE/                    # Rust reimplementation (current version)
│   ├── src/
│   │   ├── main.rs        # CLI entry point and tcpkill integration
│   │   ├── proxy.rs       # Async MITM proxy core (Tokio)
│   │   ├── capture.rs     # .rtp file I/O
│   │   ├── parser.rs      # RTSP interleaved stream parser
│   │   ├── rtp_probe.rs   # Real-time RTP parameter detection
│   │   ├── rtcp.rs        # Synthetic RTCP Sender Report generation
│   │   ├── rtsp.rs        # SETUP message scanning + Transport header rewriting
│   │   └── udp_relay.rs   # UDP socket pairs for one media track's transport
│   ├── Cargo.toml         # Rust dependencies
│   └── target/release/    # Compiled binary
│
├── NVR/                   # Minimal RTSP viewer/recorder for the PoC lab
│   ├── nvr.py             # Orchestrator (ffplay + MP4 + .rtp + web sinks, live stats)
│   ├── rtsp_client.py     # RTSP/1.0-over-TCP client with Basic + Digest auth
│   ├── rtp_depay.py       # H.264/H.265 RTP depacketizer to Annex-B
│   ├── web_server.py      # Localhost HTTP streaming server (chunked framed binary)
│   ├── web/index.html     # Browser viewer with WebCodecs decoding + live stats
│   └── README.md          # Usage
│
├── captured.rtp           # Example capture file
├── LICENSE
└── README.md              # This file
```

## Features

### Recording Mode

Available through `--mode record`.

- Listens on a specified port and forwards all RTSP traffic to the camera.
- Captures every interleaved RTP frame from the camera side.
- Saves frames to a binary `.rtp` file in a compact format.
- Supports `--capture-frames` limits.
- Supports automatic detection of codec parameters.

### Injection Mode

Available through `--mode inject`.

- Loads previously captured frames from a `.rtp` file.
- Injects frames in a loop into the downstream TCP stream toward the NVR or viewer.
- Uses RTP timestamp-based pacing so the injected video plays at the correct speed.
- Rewrites RTP sequence numbers, timestamps, and SSRC values for stream continuity.
- Supports `--inject-only` to suppress the real camera stream and show only the replay.
- Emits synthetic RTCP Sender Reports for the injected stream, on the RTCP channel
  (RTP channel + 1, per the usual `interleaved=X-Y` convention), so the wall-clock
  metadata a VMS/forensic tool would read also says "now" instead of going stale
  or silent once the real camera's RTCP stops flowing. See `--rtcp-sr-interval` below.

### Transport Support

RTSPoofing handles both transports RTSP actually negotiates, auto-detected per
session from the SETUP request — no flag needed:

- **TCP-interleaved** (`Transport: RTP/AVP/TCP;interleaved=X-Y`) — media is
  `$`-framed inside the same TCP connection as the RTSP control channel.
- **UDP** (`Transport: RTP/AVP;unicast;client_port=X-Y`) — media flows as
  independent datagrams. See "UDP Transport" under How It Works for how this
  works without ARP-spoofed traffic just being kernel-forwarded past the proxy.

### ARP Spoofing Support

- Works with `arpspoof` to transparently redirect traffic.
- Supports optional `--tcpkill-iface` to force reconnection of existing sessions and expand the testing window.

### Auto-Detection

RTSPoofing can automatically detect key RTP parameters from the capture file:

- Payload Type (PT)
- SSRC
- FPS
- Codec

Manual configuration is not required for most supported cameras.

## Installation

### Prerequisites

- Rust, for the current Rust implementation.
- Python 3.9 or later, for the Python prototype.
- Additional tools for lab testing:
  - `arpspoof`, from `dsniff`
  - `tcpdump`
  - `ffplay`

### Build the Rust Version

```bash
cd RE
cargo build --release
```

The compiled binary will be available at:

```text
RE/target/release/rtspoofing
```

### Install Python Dependencies

For the Python prototype:

```bash
cd PE
pip install scapy numpy
```

## Usage

The following examples use the Rust version.

### Record a Stream

```bash
./target/release/rtspoofing \
  --mode record \
  --listen-port 5540 \
  --camera-host 192.168.1.108 \
  --camera-port 554 \
  --capture-file captured.rtp \
  --capture-frames 500
```

### Inject a Recorded Stream

```bash
./target/release/rtspoofing \
  --mode inject \
  --listen-port 5540 \
  --camera-host 192.168.1.108 \
  --camera-port 554 \
  --capture-file captured.rtp \
  --inject-only
```

### Force Reconnection with tcpkill

Use this when an RTSP session already exists and needs to be re-established through the proxy.

```bash
./target/release/rtspoofing \
  --mode inject \
  --listen-port 5540 \
  --camera-host 192.168.1.108 \
  --capture-file captured.rtp \
  --inject-only \
  --tcpkill-iface eth0 \
  --tcpkill-delay 2
```

## Authorized Lab Workflow

The following workflow is intended for isolated lab environments or explicitly authorized security testing.

### 1. Enable IP Forwarding

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```

### 2. Start ARP Spoofing

Redirect camera-to-NVR traffic through the testing machine:

```bash
sudo arpspoof -i eth0 -t <CAMERA_IP> <NVR_IP> &
sudo arpspoof -i eth0 -t <NVR_IP> <CAMERA_IP> &
```

### 3. Redirect RTSP Traffic to the Proxy

Use this when the proxy listens on a non-standard port:

```bash
sudo iptables -t nat -A PREROUTING -p tcp --dport 554 -j REDIRECT --to-port 5540
```

### 4. Start the Proxy

Example in injection mode:

```bash
./target/release/rtspoofing \
  --mode inject \
  --listen-port 5540 \
  --camera-host <CAMERA_IP> \
  --capture-file captured.rtp \
  --inject-only
```

### 5. Connect from the NVR or Viewer

The NVR or viewer should connect to the camera as usual. The ARP spoofing setup transparently redirects the traffic through the proxy.

For testing with `ffplay`:

```bash
while true; do
    ffplay -rtsp_transport tcp "rtsp://user:pass@<CAMERA_IP>:554/stream"
    sleep 2
done
```

Or, for a demo that also records the viewer-side stream and surfaces the
on-wire state (SSRC, RTP media-clock vs. wall-clock drift, keyframe cadence),
use the bundled NVR:

```bash
python NVR/nvr.py --url rtsp://user:pass@<CAMERA_IP>:554/stream \
                  --record-mp4 session.mp4
```

See `NVR/README.md` for the rest of its options, including `--record-rtp`
to produce a loopable capture directly consumable by `--mode inject`.

## How It Works

### Capture File Format

The binary `.rtp` file stores each frame using the following format:

```text
[4B total_len][1B channel][1B reserved][2B rtp_len][N bytes RTP payload]
```

Where:

- `total_len` is `4 + rtp_len`, encoded as big-endian.
- `channel` is the interleaved channel, for example `0` for video or `1` for audio.
- `rtp_len` is the length of the RTP payload.

### Injection Pacing

The Rust version paces injection on a fixed schedule, not a naive per-frame sleep:

- Each injected frame advances the RTP timestamp by a fixed increment, `ts_per_frame`.
- Frames fire on a `tokio::time::interval` ticker anchored to a fixed start time (`1 / fps` apart),
  not `sleep(1 / fps)` re-computed after each write — the latter drifts into slow motion once
  write time is added on top of the sleep, especially with variable frame sizes.
- If a tick is missed (slow write, scheduler hiccup), the next one is simply delayed rather than
  firing a burst of catch-up frames — so a stall never turns into a flood at the NVR.
- Sending frames unpaced (as fast as the network allows) was the original approach, but it lets
  the injector outrun the NVR's receive/jitter buffer, which is a common source of dropped or
  visibly corrupted frames on the receiving end — hence the move to fixed-interval pacing.

### RTCP Sender Reports

An RTP stream carries two independent notions of time: the RTP timestamp (a 90 kHz media
clock, already rewritten for continuity — see above) and, separately, an RTCP Sender Report
carrying a wall-clock (NTP) timestamp that some VMS/forensic export tools read instead of
decoding the picture. In `--inject-only` mode nothing from the real camera reaches the NVR at
all, so without generating our own RTCP that metadata would simply go silent — the injector
fabricates a minimal SR (RC=0, no reception report blocks) per active media channel, every
`--rtcp-sr-interval` seconds (default 5s, matching typical real-world cadence), on the RTCP
channel implied by RFC 2326's `interleaved=X-Y` convention (RTCP channel = RTP channel + 1):

- `ssrc` — the same SSRC used in the injected RTP frames on that channel.
- NTP timestamp — the real wall clock at the moment the report is sent, so playback of an old
  capture is reported as happening "now," not whenever it was originally recorded.
- RTP timestamp, packet count, and octet count — kept consistent with the RTP frames actually
  sent on that channel so far.

Set `--rtcp-sr-interval 0` to disable it; the RTP-level replay works identically either way.
Note the on-screen OSD timestamp some cameras burn into the picture itself is a separate,
arguably more consequential piece of "time" — this only spoofs the RTCP metadata layer.

### UDP Transport

With ARP spoofing and `ip_forward=1` already in the lab workflow, UDP RTP/RTCP
between camera and NVR would normally just get transparently IP-forwarded by
the kernel — without ever reaching this proxy's code, which defeats the whole
point (recording/injecting requires the datagrams to actually pass through
our process). So instead of relying on that, RTSPoofing rewrites the Transport
header while relaying the SETUP request/response that's already flowing
through the (already-intercepted) RTSP TCP connection:

1. NVR sends `SETUP ... Transport: RTP/AVP;unicast;client_port=A-B` (its real
   ports). The proxy binds two of its own UDP sockets, stashes the NVR's real
   ports, and rewrites the request so the camera is told `client_port=` those
   proxy-owned ports instead — the camera now unknowingly sends its RTP/RTCP
   to us.
2. Camera replies with its own `server_port=C-D`. The proxy binds two more UDP
   sockets, rewrites the response's `client_port=` back to the NVR's real A-B
   (so the NVR isn't confused seeing its own ports echoed differently) and its
   `server_port=` to *another* pair of proxy-owned ports — the NVR now
   unknowingly sends its RTCP receiver reports to us too, instead of straight
   to the camera.
3. From there it's four sockets per track: two the camera was told about
   (receiving its real RTP/RTCP), two the NVR was told about (receiving its
   RTCP reports, and used as the *source* when relaying/injecting media
   toward the NVR — some implementations validate that incoming RTP/RTCP
   actually comes from the declared server_port).

Record and inject work identically to the TCP-interleaved path from there —
same `.rtp` capture format, same `RTPProbe` auto-detection, same fixed-interval
pacing, same synthetic RTCP SR — `process_camera_frame` in `proxy.rs` is the
shared logic both transports call into. One session is treated as either
fully TCP-interleaved or fully UDP (decided by the first SETUP seen); proxy
UDP ports are OS-assigned ephemeral, and the RTSP parsing here is intentionally
scoped to finding CSeq/Transport in SETUP messages, not a full RFC 2326 parser.

### Auto-Parameter Detection

`RTPProbe` analyzes the first frames of the live stream to detect:

- Payload Type (PT)
- SSRC
- Codec, such as H.264 or H.265
- Frame rate (FPS)

These parameters are then used for smoother injection and stream continuity.

## Performance

- Rust version: approximately 300 Mbps throughput, suitable for high-resolution streams.
- Fixed-interval injection pacing reduces jitter, slow-motion drift, and burst-induced frame drops.
- Session stats (bytes/frames counters) are lock-free atomics rather than an async mutex shared
  across every packet on the relay path.
- `.rtp` capture writes happen on a dedicated blocking task, decoupled from the live relay via a
  bounded channel, so disk I/O latency can no longer stall the camera→NVR forwarding path.
- `--capture-frames` now actually stops writing to disk once the limit is reached (the live
  relay keeps running); previously the limit was logged but never enforced.

## Running the Rust Test Suite

```bash
cd RE
cargo test --release
```

Unit tests live alongside the code they cover (`#[cfg(test)] mod tests` in each
file — standard practice for a binary crate with no separate `lib.rs`), and are
scoped to the pure/deterministic logic: the interleaved-frame parser, RTP
header parsing/rewriting, RTCP SR construction, SETUP message scanning and
Transport-header rewriting, and the `.rtp` capture file format (including a
real write-then-read round trip through a temp file). They don't cover the
async networking in `proxy.rs`/`udp_relay.rs` directly — that's exercised by
end-to-end runs against a real or simulated camera/NVR instead.

## Testing the Python Prototype

The original Python prototype, located at `PE/RTSPoofing.py`, can be used for quick experiments:

```bash
cd PE
python RTSPoofing.py \
  --mode record \
  --listen-port 5540 \
  --camera-host 192.168.1.108 \
  --capture-file captured.rtp \
  --capture-frames 200
```

## Security Considerations

- ARP spoofing is noisy and may be detected by network monitoring tools.
- Use this tool only in isolated lab environments or with explicit authorization.
- The project is intended for research and educational purposes.
- Encrypted streams, such as RTSPS, are not supported by default and would require TLS integration.

## Contributing

Contributions are welcome. Potential areas for improvement include:

- RTP/UDP support for non-interleaved streams.
- TLS support for RTSPS.
- Configuration file support using YAML or TOML.
- Unit and integration tests.
- A web dashboard for real-time monitoring.

## License

This project is licensed under the MIT License. See the [`LICENSE`](LICENSE) file for details.