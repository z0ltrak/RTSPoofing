#!/usr/bin/env python3
"""
Live RTSP/TCP interleaved RTP relay to ffmpeg HLS.

Use case:
  Sniff RTSP-over-TCP traffic between an IP camera and an NVR/VMS, extract
  interleaved RTP frames ($ channel length RTP...), relay the original RTP
  packets to localhost UDP, and let ffmpeg's RTP demuxer/depacketizer handle
  H.264/H.265 correctly. This avoids fragile manual Annex-B reconstruction.

Authorized use only.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import subprocess
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    from scapy.all import IP, IPv6, TCP, Raw, sniff, get_if_list
except ImportError:
    print("[!] Missing dependency: scapy")
    print("    Install with: python -m pip install scapy")
    sys.exit(1)

FlowKey = Tuple[str, int, str, int]


def ip_pair(pkt):
    if IP in pkt:
        return pkt[IP].src, pkt[IP].dst
    if IPv6 in pkt:
        return pkt[IPv6].src, pkt[IPv6].dst
    return None, None


def rtp_payload_type(rtp: bytes) -> Optional[int]:
    if len(rtp) < 12:
        return None
    if (rtp[0] >> 6) != 2:
        return None
    return rtp[1] & 0x7F


def rtp_ssrc(rtp: bytes) -> Optional[int]:
    if len(rtp) < 12:
        return None
    if (rtp[0] >> 6) != 2:
        return None
    return struct.unpack("!I", rtp[8:12])[0]


def rtp_seq(rtp: bytes) -> Optional[int]:
    if len(rtp) < 12:
        return None
    return struct.unpack("!H", rtp[2:4])[0]


def looks_like_rtp(rtp: bytes, pt_filter: Optional[int], ssrc_filter: Optional[int]) -> bool:
    if len(rtp) < 12:
        return False
    if (rtp[0] >> 6) != 2:
        return False
    pt = rtp[1] & 0x7F
    # Exclude common RTCP types when accidentally parsed as RTP.
    if pt in {72, 73, 74, 75, 76, 77}:
        # Not a perfect test, but filters common false positives.
        pass
    if pt_filter is not None and pt != pt_filter:
        return False
    ssrc = rtp_ssrc(rtp)
    if ssrc_filter is not None and ssrc != ssrc_filter:
        return False
    return True


class InterleavedParser:
    def __init__(self, args, relay_sock: socket.socket, relay_addr: Tuple[str, int], raw_file=None):
        self.args = args
        self.relay_sock = relay_sock
        self.relay_addr = relay_addr
        self.raw_file = raw_file
        self.buf = bytearray()
        self.frames = 0
        self.relayed = 0
        self.filtered = 0
        self.bytes_relayed = 0
        self.last_seq = None
        self.gaps = 0
        self.channel_counts = defaultdict(int)
        self.pt_counts = defaultdict(int)
        self.ssrc_counts = defaultdict(int)
        self.last_status = time.time()

    def feed(self, data: bytes):
        if not data:
            return
        self.buf.extend(data)
        self._parse()

    def _parse(self):
        max_frame = self.args.max_interleaved_frame
        while True:
            idx = self.buf.find(b"$")
            if idx < 0:
                # Keep a few bytes for a possible split '$' frame marker.
                if len(self.buf) > 3:
                    del self.buf[:-3]
                return
            if idx > 0:
                del self.buf[:idx]
            if len(self.buf) < 4:
                return
            channel = self.buf[1]
            length = struct.unpack("!H", self.buf[2:4])[0]
            if length < 8 or length > max_frame:
                # False '$' in RTSP text or damaged sync. Skip one byte and resync.
                del self.buf[0]
                continue
            if len(self.buf) < 4 + length:
                return
            frame = bytes(self.buf[4:4 + length])
            del self.buf[:4 + length]
            self.frames += 1
            self.channel_counts[channel] += 1

            if self.args.channel is not None and channel != self.args.channel:
                self.filtered += 1
                continue
            if not looks_like_rtp(frame, self.args.pt, self.args.ssrc_int):
                self.filtered += 1
                continue

            pt = rtp_payload_type(frame)
            ssrc = rtp_ssrc(frame)
            seq = rtp_seq(frame)
            if pt is not None:
                self.pt_counts[pt] += 1
            if ssrc is not None:
                self.ssrc_counts[ssrc] += 1
            if seq is not None:
                if self.last_seq is not None:
                    expected = (self.last_seq + 1) & 0xFFFF
                    if seq != expected:
                        self.gaps += 1
                self.last_seq = seq

            try:
                self.relay_sock.sendto(frame, self.relay_addr)
                self.relayed += 1
                self.bytes_relayed += len(frame)
                if self.raw_file:
                    # Debug only: save RTP packets, not Annex-B. Includes a tiny header.
                    self.raw_file.write(struct.pack("!I", len(frame)) + frame)
                    self.raw_file.flush()
            except OSError as e:
                print(f"[!] UDP relay send failed: {e}")

    def status_line(self) -> str:
        top_ch = ",".join(f"{k}:{v}" for k, v in sorted(self.channel_counts.items(), key=lambda kv: -kv[1])[:4])
        top_pt = ",".join(f"{k}:{v}" for k, v in sorted(self.pt_counts.items(), key=lambda kv: -kv[1])[:4])
        top_ssrc = ",".join(f"0x{k:08x}:{v}" for k, v in sorted(self.ssrc_counts.items(), key=lambda kv: -kv[1])[:3])
        return (f"frames={self.frames} relayed={self.relayed} filtered={self.filtered} "
                f"bytes={self.bytes_relayed} gaps={self.gaps} channels=[{top_ch}] "
                f"pt=[{top_pt}] ssrc=[{top_ssrc}] buf={len(self.buf)}")


class TCPAssembler:
    def __init__(self, parser: InterleavedParser):
        self.parser = parser
        self.next_seq: Optional[int] = None
        self.pending: Dict[int, bytes] = {}
        self.last_progress = time.time()

    def feed_segment(self, seq: int, payload: bytes):
        if not payload:
            return
        if self.next_seq is None:
            self.next_seq = seq
        end_seq = seq + len(payload)

        if seq < self.next_seq:
            # Duplicate or overlapping segment.
            overlap = self.next_seq - seq
            if overlap >= len(payload):
                return
            payload = payload[overlap:]
            seq = self.next_seq
            end_seq = seq + len(payload)

        if seq > self.next_seq:
            # Out-of-order. Store and wait, but cap memory.
            self.pending[seq] = payload
            if len(self.pending) > 512:
                # If we are missing data forever, jump to the earliest pending segment.
                first = min(self.pending)
                self.next_seq = first
                payload = self.pending.pop(first)
                self._accept(payload)
            return

        self._accept(payload)
        self.next_seq = end_seq

        while self.next_seq in self.pending:
            p = self.pending.pop(self.next_seq)
            self._accept(p)
            self.next_seq += len(p)

    def _accept(self, payload: bytes):
        self.last_progress = time.time()
        self.parser.feed(payload)


def make_sdp(path: Path, codec: str, pt: int, port: int, fmtp: Optional[str] = None):
    codec_name = "H265" if codec.lower() in {"h265", "hevc"} else "H264"
    lines = [
        "v=0",
        "o=- 0 0 IN IP4 127.0.0.1",
        "s=Sniffed RTP Relay",
        "c=IN IP4 127.0.0.1",
        "t=0 0",
        f"m=video {port} RTP/AVP {pt}",
        f"a=rtpmap:{pt} {codec_name}/90000",
        "a=recvonly",
    ]
    if fmtp:
        if fmtp.startswith("a=fmtp:"):
            lines.append(fmtp)
        else:
            lines.append(f"a=fmtp:{pt} {fmtp}")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


def build_ffmpeg_cmd(args, sdp_path: Path):
    out_dir = Path(args.convert_output)
    out_dir.mkdir(parents=True, exist_ok=True)
    segment_pattern = str(out_dir / "segment_%05d.ts")
    playlist = str(out_dir / "live.m3u8")

    cmd = [
        args.ffmpeg, "-hide_banner", "-loglevel", args.ffmpeg_loglevel,
        "-protocol_whitelist", "file,udp,rtp",
        "-fflags", "+genpts+nobuffer",
        "-flags", "low_delay",
        "-analyzeduration", str(args.analyzeduration),
        "-probesize", str(args.probesize),
        "-i", str(sdp_path),
        "-an",
    ]

    if args.codec.lower() in {"h264", "avc"} and args.copy_h264:
        cmd += ["-c:v", "copy"]
    else:
        cmd += [
            "-c:v", args.encoder,
        ]
        if args.encoder == "libx264":
            cmd += [
                "-preset", args.x264_preset,
                "-tune", "zerolatency",
                "-pix_fmt", "yuv420p",
                "-profile:v", args.x264_profile,
                "-g", str(args.gop),
                "-keyint_min", str(args.gop),
                "-sc_threshold", "0",
            ]

    cmd += [
        "-flush_packets", "1",
        "-f", "hls",
        "-hls_time", str(args.hls_time),
        "-hls_list_size", str(args.hls_list_size),
        "-hls_flags", "delete_segments+append_list+program_date_time+independent_segments",
        "-hls_segment_type", "mpegts",
        "-hls_segment_filename", segment_pattern,
        playlist,
    ]
    return cmd, playlist


def start_ffmpeg(args, sdp_path: Path):
    cmd, playlist = build_ffmpeg_cmd(args, sdp_path)
    log_path = Path(args.ffmpeg_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True) if log_path.parent != Path('.') else None
    log = open(log_path, "ab", buffering=0)
    header = f"\n===== ffmpeg started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\nCommand: {' '.join(cmd)}\n".encode()
    log.write(header)
    print("[*] Starting ffmpeg RTP->HLS:")
    print("    " + " ".join(cmd))
    print(f"[*] HLS playlist target: {playlist}")
    print(f"[*] ffmpeg log: {log_path}")
    proc = subprocess.Popen(cmd, stdout=log, stderr=log)
    return proc, log


def tail_file(path: Path, max_lines: int = 80) -> str:
    try:
        data = path.read_text(errors="replace")
    except Exception as e:
        return f"<could not read log: {e}>"
    lines = data.splitlines()
    return "\n".join(lines[-max_lines:])


def parse_ssrc(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    return int(value, 0)


def main():
    ap = argparse.ArgumentParser(description="Relay RTSP/TCP interleaved RTP to ffmpeg HLS for browser viewing.")
    ap.add_argument("--list-ifaces", action="store_true", help="List Scapy interfaces and exit")
    ap.add_argument("--iface", help="Interface name, e.g. Wi-Fi or Ethernet")
    ap.add_argument("--bpf", default="port 554", help="BPF filter for sniffing")
    ap.add_argument("--codec", choices=["h264", "h265", "hevc"], required=False, default="h265")
    ap.add_argument("--channel", type=int, default=None, help="RTSP interleaved channel to relay, e.g. 0")
    ap.add_argument("--pt", type=int, default=None, help="RTP payload type to relay, e.g. 98")
    ap.add_argument("--ssrc", dest="ssrc", default=None, help="RTP SSRC to relay, e.g. 0x9348347d")
    ap.add_argument("--local-rtp-port", type=int, default=5004)
    ap.add_argument("--convert-output", default="live_hls")
    ap.add_argument("--hls-time", type=float, default=1.0)
    ap.add_argument("--hls-list-size", type=int, default=6)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffmpeg-log-file", default="ffmpeg_rtp_relay_hls.log")
    ap.add_argument("--ffmpeg-loglevel", default="info")
    ap.add_argument("--encoder", default="libx264", help="H.264 encoder for browser HLS, e.g. libx264, h264_mf, h264_nvenc")
    ap.add_argument("--copy-h264", action="store_true", help="If input is H.264, copy instead of transcoding")
    ap.add_argument("--x264-preset", default="ultrafast")
    ap.add_argument("--x264-profile", default="baseline")
    ap.add_argument("--gop", type=int, default=25)
    ap.add_argument("--analyzeduration", type=int, default=10000000)
    ap.add_argument("--probesize", type=int, default=10000000)
    ap.add_argument("--status-interval", type=float, default=1.0)
    ap.add_argument("--output-rtp", default=None, help="Optional debug file containing length-prefixed RTP packets")
    ap.add_argument("--sdp-file", default="relay_input.sdp")
    ap.add_argument("--max-interleaved-frame", type=int, default=262144)
    ap.add_argument("--no-ffmpeg", action="store_true", help="Only relay RTP to UDP; do not start ffmpeg")
    args = ap.parse_args()
    args.ssrc_int = parse_ssrc(args.ssrc)

    if args.list_ifaces:
        for i, iface in enumerate(get_if_list()):
            print(f"{i}: {iface}")
        return

    if args.pt is None:
        print("[!] --pt is strongly recommended/required for SDP. Use the PT from probe, e.g. --pt 98")
        sys.exit(2)
    if not args.iface:
        print("[!] --iface is required, or use --list-ifaces")
        sys.exit(2)

    out_dir = Path(args.convert_output)
    out_dir.mkdir(parents=True, exist_ok=True)
    sdp_path = Path(args.sdp_file)
    if not sdp_path.is_absolute():
        sdp_path = out_dir / sdp_path
    make_sdp(sdp_path, args.codec, args.pt, args.local_rtp_port)
    print("[*] SDP written:", sdp_path)
    print(sdp_path.read_text())

    relay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    relay_addr = ("127.0.0.1", args.local_rtp_port)

    raw_file = open(args.output_rtp, "ab", buffering=0) if args.output_rtp else None
    parser = InterleavedParser(args, relay_sock, relay_addr, raw_file=raw_file)
    assemblers: Dict[FlowKey, TCPAssembler] = {}

    ffmpeg_proc = None
    ffmpeg_log = None
    if not args.no_ffmpeg:
        ffmpeg_proc, ffmpeg_log = start_ffmpeg(args, sdp_path)

    last_status = time.time()

    def handle(pkt):
        nonlocal last_status, ffmpeg_proc
        if TCP not in pkt or Raw not in pkt:
            return
        src, dst = ip_pair(pkt)
        if not src or not dst:
            return
        sport = int(pkt[TCP].sport)
        dport = int(pkt[TCP].dport)
        payload = bytes(pkt[Raw].load)
        seq = int(pkt[TCP].seq)
        key: FlowKey = (src, sport, dst, dport)
        if key not in assemblers:
            assemblers[key] = TCPAssembler(parser)
        assemblers[key].feed_segment(seq, payload)

        now = time.time()
        if now - last_status >= args.status_interval:
            last_status = now
            status = parser.status_line()
            ff = ""
            if ffmpeg_proc is not None:
                rc = ffmpeg_proc.poll()
                ff = " ffmpeg=running" if rc is None else f" ffmpeg_exited={rc}"
                if rc is not None:
                    print("[!] ffmpeg exited. Last log lines:")
                    print(tail_file(Path(args.ffmpeg_log_file)))
            print(f"[*] relay: {status}{ff}")

    print("[*] Starting sniff")
    print(f"    iface: {args.iface}")
    print(f"    bpf  : {args.bpf}")
    print(f"    filter: channel={args.channel} pt={args.pt} ssrc={args.ssrc or 'any'}")
    print("[*] This relays original RTP packets to ffmpeg; no manual H.265 Annex-B reconstruction is used.")
    print("[*] Use only on traffic you are authorized to monitor.")
    try:
        sniff(iface=args.iface, filter=args.bpf, prn=handle, store=False)
    except KeyboardInterrupt:
        print("\n[*] Stopping...")
    finally:
        if raw_file:
            raw_file.close()
        if ffmpeg_proc is not None and ffmpeg_proc.poll() is None:
            ffmpeg_proc.terminate()
        if ffmpeg_log:
            ffmpeg_log.close()
        relay_sock.close()


if __name__ == "__main__":
    main()
