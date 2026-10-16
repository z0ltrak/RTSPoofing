# NVR — minimal RTSP viewer/recorder for the RTSPoofing lab

A small Python 3 RTSP client that plays the role of the "NVR / viewer" in the
PoC's lab topology:

```
Camera ──TCP:554──► MITM proxy (RE/ or PE/) ──TCP:554──► NVR (this)
```

It connects to an RTSP IP camera (directly or through the MITM proxy),
negotiates TCP-interleaved transport — the exact path the proxy intercepts —
depacketizes the RTP video stream into an H.264 or H.265 Annex-B elementary
stream, and from there:

- pipes the stream to `ffplay` for a live window (toggle with `--no-display`),
- optionally records it to MP4 via `ffmpeg -c copy` (no re-encode),
- optionally dumps a `.rtp` capture in **the proxy's own binary format**, so
  the file is directly loop-injectable with `rtspoofing --mode inject`.

A one-line live status is printed to stderr while the stream is running:
frames received, SSRC, RTP media-clock time, wall-clock elapsed, and the
drift between the two — the quantities that make injection/replay visible
on a running demo.

## Reconnect behaviour

The NVR reconnects on its own when the stream is interrupted — connect
timeouts, mid-stream TCP resets, and silent stalls (no RTP arriving for
`--stall-timeout` seconds) all trigger a retry after `--reconnect-delay`
seconds. Each attempt is numbered in the log; `--record-mp4` and
`--record-rtp` paths get a `.NNN` index inserted before the extension on
attempts 2+ so each session is a self-contained file. The retry loop is
infinite by default; use `--max-reconnects N` to bound it, or
`--no-reconnect` to exit on the first failure.

Permanent errors (bad SDP, unsupported codec, RTSP 4xx after auth) exit
with status 2 instead of retrying — those won't fix themselves. SIGTERM
and Ctrl-C always exit cleanly.

## Why not just `ffplay`?

The current lab workflow in the top-level README uses

```bash
while true; do ffplay -rtsp_transport tcp "rtsp://.../stream"; sleep 2; done
```

which is fine for a smoke test but hides everything interesting about the
attack:

- `ffplay` reconnects silently on error, so transport-layer events are
  invisible;
- there's nothing to record, so you can't go back and inspect what the NVR
  actually saw during a replay;
- the SSRC / RTP timestamp / packet rate are not exposed, so a successful
  injection looks indistinguishable from a healthy real stream.

This NVR fills those gaps while staying small enough to read in an afternoon.

## Requirements

- Python ≥ 3.9 (standard library only — no `pip install` needed)
- `ffplay` and `ffmpeg` on `PATH` (both from the FFmpeg project), for the
  display and MP4 recording sinks respectively. If one is missing, the
  corresponding sink is skipped with a warning and the rest keeps running.

## Usage

### Live view through the MITM proxy

```bash
python nvr.py --url rtsp://admin:admin@127.0.0.1:5540/stream
```

If the proxy is running in `--mode inject --inject-only`, this is what sees
only the replayed capture; if it's running in `--mode record`, this is what
drives the camera to actually emit the stream the proxy is capturing.

### Live view + continuous MP4 recording

```bash
python nvr.py \
  --url rtsp://admin:admin@192.168.1.108:554/stream \
  --record-mp4 session.mp4
```

The MP4 is written with `-c copy -movflags +faststart+frag_keyframe+empty_moov`
so it stays playable even if the process is killed mid-stream.

### Headless capture of a loopable `.rtp` file

```bash
python nvr.py \
  --url rtsp://admin:admin@192.168.1.108:554/stream \
  --no-display \
  --record-rtp loopable.rtp
```

The output file follows the exact binary layout documented in the top-level
README ("Capture File Format") and already parsed by `PE/RTSPoofing.py` and
`RE/src/capture.rs`, so it feeds the proxy's inject mode without any
conversion:

```bash
../RE/target/release/rtspoofing \
  --mode inject \
  --listen-port 5540 \
  --camera-host 192.168.1.108 \
  --capture-file loopable.rtp \
  --inject-only
```

## What's inside

- `rtsp_client.py` — RTSP/1.0 over TCP: `OPTIONS → DESCRIBE → SETUP → PLAY`,
  Basic + Digest (MD5 / MD5-SESS) auth from a `WWW-Authenticate` challenge,
  SDP parsing for a single `m=video` track, `GET_PARAMETER` keepalive, and
  an `iter_interleaved(sock)` generator that yields RTP packets and
  non-interleaved text from the TCP stream.
- `rtp_depay.py` — RTP header parsing (CSRC + extension + padding), plus
  depacketizers for H.264 (RFC 6184: single NAL, STAP-A, FU-A) and H.265
  (RFC 7798: single NAL, AP, FU). Emits Annex-B NALUs with `00 00 00 01`
  start codes, with the SDP-advertised SPS/PPS (and VPS for HEVC) prepended
  once so the decoder can start before the first in-band parameter set.
- `nvr.py` — the orchestrator: brings up the RTSP session, fans the
  depacketized stream out to `ffplay` and/or `ffmpeg`, writes the `.rtp`
  capture, prints the live stats line, tears everything down on SIGINT.

## Scope and non-goals

This is a demo-grade NVR. It handles the one case the PoC needs — a single
H.264 or H.265 video track over RTSP-interleaved TCP — and nothing else:

- No audio track handling (the audio RTP channel is counted and optionally
  written to `.rtp` so the resulting capture is loop-compatible, but not
  decoded).
- No RTSPS / SRTP.
- No multi-track multiplexing, no interleaved UDP fallback, no RTCP RR back
  to the sender.
- No motion detection, event recording, or clip indexing. For a real NVR
  you want a VMS; for the PoC, this is deliberately the smallest thing
  that makes the attack chain visible end to end.
