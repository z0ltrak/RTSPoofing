//! rtcp.rs — Minimal RTCP Sender Report (SR) support.
//!
//! An RTP stream normally carries a companion RTCP channel where the sender
//! periodically reports a wall-clock (NTP) timestamp alongside the RTP media
//! clock, so a receiver can map "RTP timestamp X" to "real time Y" — e.g. for
//! a VMS/forensic export tool that reads the wall clock instead of decoding
//! the picture. This module builds synthetic SR packets that keep that NTP
//! clock walking forward in real time for whatever we're injecting, using
//! RFC 2326's convention that the RTCP channel is the RTP channel's number + 1.

use std::time::{SystemTime, UNIX_EPOCH};

const RTCP_VERSION: u8 = 2;
const PT_SR: u8 = 200;

/// Seconds between the NTP epoch (1900-01-01) and the Unix epoch (1970-01-01).
const NTP_UNIX_EPOCH_OFFSET: u64 = 2_208_988_800;

/// Current wall-clock time as a 64-bit NTP timestamp: (seconds, fraction).
pub fn ntp_now() -> (u32, u32) {
    let since_epoch = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let ntp_secs = since_epoch.as_secs().wrapping_add(NTP_UNIX_EPOCH_OFFSET) as u32;
    let ntp_frac = ((since_epoch.subsec_nanos() as u64) << 32) / 1_000_000_000;
    (ntp_secs, ntp_frac as u32)
}

/// The RTCP channel that accompanies an RTP media channel, per the usual
/// `interleaved=X-Y` (Y = X+1) convention used by RTSP-over-TCP.
#[inline]
pub fn rtcp_channel_for(media_channel: u8) -> u8 {
    if media_channel % 2 == 0 { media_channel + 1 } else { media_channel }
}

/// Build a minimal RTCP Sender Report (RC = 0, no reception report blocks).
///
/// Layout (RFC 3550 §6.4.1), 28 bytes total:
/// ```text
/// byte 0..4   header: V=2,P=0,RC=0 | PT=200 | length=6 (words after first, i.e. 28/4 - 1)
/// byte 4..8   SSRC of sender
/// byte 8..12  NTP timestamp, seconds
/// byte 12..16 NTP timestamp, fraction
/// byte 16..20 RTP timestamp (same clock as the media stream at this instant)
/// byte 20..24 sender's packet count
/// byte 24..28 sender's octet count
/// ```
pub fn build_sr(ssrc: u32, ntp_secs: u32, ntp_frac: u32, rtp_ts: u32, pkt_count: u32, octet_count: u32) -> Vec<u8> {
    let mut out = Vec::with_capacity(28);
    out.push(RTCP_VERSION << 6); // V=2, P=0, RC=0
    out.push(PT_SR);
    out.extend_from_slice(&6u16.to_be_bytes()); // length in 32-bit words, minus 1
    out.extend_from_slice(&ssrc.to_be_bytes());
    out.extend_from_slice(&ntp_secs.to_be_bytes());
    out.extend_from_slice(&ntp_frac.to_be_bytes());
    out.extend_from_slice(&rtp_ts.to_be_bytes());
    out.extend_from_slice(&pkt_count.to_be_bytes());
    out.extend_from_slice(&octet_count.to_be_bytes());
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rtcp_channel_for_uses_next_odd_channel() {
        assert_eq!(rtcp_channel_for(0), 1);
        assert_eq!(rtcp_channel_for(2), 3);
        assert_eq!(rtcp_channel_for(254), 255);
    }

    #[test]
    fn rtcp_channel_for_odd_input_returns_itself() {
        // Not a real-world input (RTP channels are conventionally even), but
        // the function must degrade sanely rather than panic or overflow.
        assert_eq!(rtcp_channel_for(1), 1);
    }

    #[test]
    fn build_sr_produces_correct_28_byte_layout() {
        let sr = build_sr(0xC0FFEE01, 0x11111111, 0x22222222, 0x33333333, 100, 5000);
        assert_eq!(sr.len(), 28);
        assert_eq!(sr[0] >> 6, 2, "RTCP version must be 2");
        assert_eq!(sr[1], 200, "packet type must be SR (200)");
        assert_eq!(u16::from_be_bytes([sr[2], sr[3]]), 6, "length field must be 6 words");
        assert_eq!(u32::from_be_bytes(sr[4..8].try_into().unwrap()), 0xC0FFEE01, "ssrc");
        assert_eq!(u32::from_be_bytes(sr[8..12].try_into().unwrap()), 0x11111111, "ntp seconds");
        assert_eq!(u32::from_be_bytes(sr[12..16].try_into().unwrap()), 0x22222222, "ntp fraction");
        assert_eq!(u32::from_be_bytes(sr[16..20].try_into().unwrap()), 0x33333333, "rtp timestamp");
        assert_eq!(u32::from_be_bytes(sr[20..24].try_into().unwrap()), 100, "packet count");
        assert_eq!(u32::from_be_bytes(sr[24..28].try_into().unwrap()), 5000, "octet count");
    }

    #[test]
    fn ntp_now_is_in_a_plausible_current_range() {
        let (secs, _frac) = ntp_now();
        let unix_secs = secs as u64 - NTP_UNIX_EPOCH_OFFSET;
        // Anywhere between 2020-01-01 and 2100-01-01 in Unix time.
        assert!(unix_secs > 1_577_836_800, "NTP timestamp looks too far in the past");
        assert!(unix_secs < 4_102_444_800, "NTP timestamp looks implausibly far in the future");
    }
}
