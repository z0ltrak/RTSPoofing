"""
RTP depacketizer for H.264 and H.265 into an Annex-B elementary stream.

Scope: only what a surveillance camera actually emits over RTSP-interleaved
transport — single NAL, STAP-A/AP aggregation, FU-A/FU fragmentation. No SVC,
no MVC, no robust-reassembly. If a NAL arrives fragmented across packets with
losses in the middle, the fragment is dropped (the H.264 decoder would reject
it anyway).

Public API:

    depay = RtpDepayH264(sps_pps=[b"\\x67\\x42...", b"\\x68\\xce..."])
    depay = RtpDepayH265(vps_sps_pps=[b"...", b"...", b"..."])
    for nalus in depay.feed(rtp_payload, marker):
        annex_b.write(nalus)   # already prefixed with 00 00 00 01
"""

from __future__ import annotations

import struct
from typing import Iterator, Optional

RTP_HEADER_MIN = 12
START_CODE = b"\x00\x00\x00\x01"


def parse_rtp(packet: bytes) -> Optional[dict]:
    """Return parsed RTP header + payload slice, or None if malformed."""
    if len(packet) < RTP_HEADER_MIN:
        return None
    b0 = packet[0]
    version = b0 >> 6
    if version != 2:
        return None
    cc = b0 & 0x0F
    has_ext = bool(b0 & 0x10)
    padding = bool(b0 & 0x20)

    b1 = packet[1]
    marker = bool(b1 & 0x80)
    pt = b1 & 0x7F

    seq = struct.unpack_from("!H", packet, 2)[0]
    ts = struct.unpack_from("!I", packet, 4)[0]
    ssrc = struct.unpack_from("!I", packet, 8)[0]

    offset = 12 + 4 * cc
    if has_ext:
        if len(packet) < offset + 4:
            return None
        ext_len = struct.unpack_from("!H", packet, offset + 2)[0]
        offset += 4 + 4 * ext_len

    end = len(packet)
    if padding and end > offset:
        pad_count = packet[end - 1]
        if pad_count and end - pad_count >= offset:
            end -= pad_count

    if offset > end:
        return None
    return {
        "pt": pt,
        "marker": marker,
        "seq": seq,
        "ts": ts,
        "ssrc": ssrc,
        "payload": packet[offset:end],
    }


class _FragmentAssembler:
    """Shared FU reassembly state."""

    __slots__ = ("buf", "started", "expected_seq")

    def __init__(self) -> None:
        self.buf = bytearray()
        self.started = False
        self.expected_seq: Optional[int] = None

    def reset(self) -> None:
        self.buf.clear()
        self.started = False
        self.expected_seq = None


class RtpDepayH264:
    """RFC 6184 depacketizer. feed() yields complete NAL units framed as Annex-B."""

    # NAL unit types we care about for packetization dispatch.
    NAL_STAP_A = 24
    NAL_FU_A = 28

    def __init__(self, sps_pps: Optional[list[bytes]] = None) -> None:
        self._fu = _FragmentAssembler()
        # Prepend out-of-band SPS/PPS from the SDP once, so the decoder can
        # start on the first keyframe without needing to wait for an in-band
        # parameter set.
        self._prelude = b"".join(START_CODE + nal for nal in (sps_pps or []))

    def take_prelude(self) -> bytes:
        p, self._prelude = self._prelude, b""
        return p

    def reset_fragments(self) -> None:
        """
        Drop any in-progress FU-A reassembly. Called at session boundaries
        (SSRC change, injection switch) so a half-received fragment from the
        previous session isn't completed with a packet from the new one.
        """
        self._fu.reset()

    def feed(self, payload: bytes, seq: int) -> Iterator[bytes]:
        if not payload:
            return
        nal_header = payload[0]
        nal_type = nal_header & 0x1F

        if 1 <= nal_type <= 23:
            self._fu.reset()
            yield START_CODE + payload
            return

        if nal_type == self.NAL_STAP_A:
            self._fu.reset()
            offset = 1
            while offset + 2 <= len(payload):
                size = struct.unpack_from("!H", payload, offset)[0]
                offset += 2
                if offset + size > len(payload):
                    return
                yield START_CODE + payload[offset:offset + size]
                offset += size
            return

        if nal_type == self.NAL_FU_A:
            if len(payload) < 2:
                return
            fu_indicator = nal_header
            fu_header = payload[1]
            start = bool(fu_header & 0x80)
            end = bool(fu_header & 0x40)
            inner_type = fu_header & 0x1F

            if start:
                nri = fu_indicator & 0x60
                reconstructed = bytes([nri | inner_type])
                self._fu.buf = bytearray(reconstructed)
                self._fu.buf.extend(payload[2:])
                self._fu.started = True
                self._fu.expected_seq = (seq + 1) & 0xFFFF
                return

            if not self._fu.started:
                return  # mid-fragment arrived without a start — drop.
            if self._fu.expected_seq is not None and seq != self._fu.expected_seq:
                self._fu.reset()
                return
            self._fu.buf.extend(payload[2:])
            self._fu.expected_seq = (seq + 1) & 0xFFFF
            if end:
                nalu = bytes(self._fu.buf)
                self._fu.reset()
                yield START_CODE + nalu
            return

        # MTAP/other aggregation modes not implemented — surveillance cameras
        # don't use them in practice. Silently drop so playback keeps running.
        return


class RtpDepayH265:
    """RFC 7798 depacketizer. feed() yields complete NAL units framed as Annex-B."""

    NAL_AP = 48    # Aggregation Packet
    NAL_FU = 49    # Fragmentation Unit
    NAL_PACI = 50  # not implemented

    def __init__(self, vps_sps_pps: Optional[list[bytes]] = None) -> None:
        self._fu = _FragmentAssembler()
        self._prelude = b"".join(START_CODE + nal for nal in (vps_sps_pps or []))

    def take_prelude(self) -> bytes:
        p, self._prelude = self._prelude, b""
        return p

    def reset_fragments(self) -> None:
        """Drop any in-progress FU reassembly (see RtpDepayH264.reset_fragments)."""
        self._fu.reset()

    def feed(self, payload: bytes, seq: int) -> Iterator[bytes]:
        if len(payload) < 2:
            return
        hdr0 = payload[0]
        hdr1 = payload[1]
        nal_type = (hdr0 >> 1) & 0x3F

        if 0 <= nal_type <= 47:
            self._fu.reset()
            yield START_CODE + payload
            return

        if nal_type == self.NAL_AP:
            self._fu.reset()
            offset = 2
            while offset + 2 <= len(payload):
                size = struct.unpack_from("!H", payload, offset)[0]
                offset += 2
                if offset + size > len(payload):
                    return
                yield START_CODE + payload[offset:offset + size]
                offset += size
            return

        if nal_type == self.NAL_FU:
            if len(payload) < 3:
                return
            fu_header = payload[2]
            start = bool(fu_header & 0x80)
            end = bool(fu_header & 0x40)
            inner_type = fu_header & 0x3F

            if start:
                # Reconstruct a 2-byte HEVC NAL header with the inner nal type.
                new_hdr0 = (hdr0 & 0x81) | (inner_type << 1)
                reconstructed = bytes([new_hdr0, hdr1])
                self._fu.buf = bytearray(reconstructed)
                self._fu.buf.extend(payload[3:])
                self._fu.started = True
                self._fu.expected_seq = (seq + 1) & 0xFFFF
                return

            if not self._fu.started:
                return
            if self._fu.expected_seq is not None and seq != self._fu.expected_seq:
                self._fu.reset()
                return
            self._fu.buf.extend(payload[3:])
            self._fu.expected_seq = (seq + 1) & 0xFFFF
            if end:
                nalu = bytes(self._fu.buf)
                self._fu.reset()
                yield START_CODE + nalu
            return

        return
