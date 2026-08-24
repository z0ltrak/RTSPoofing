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
│   │   └── rtcp.rs        # Synthetic RTCP Sender Report generation
│   ├── Cargo.toml         # Rust dependencies
│   └── target/release/    # Compiled binary
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