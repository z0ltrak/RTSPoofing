//! rtp_probe.rs — Real-time RTP stream parameter detection.
//!
//! Equivalent of rtp_probe.py: feeds RTP frames during the warm-up window
//! and extracts PT, SSRC, codec, and FPS automatically before injection starts.
//! Designed to be called from a single async task; no internal locking needed.

use std::collections::HashMap;
use std::time::{Duration, Instant};
use tracing::{debug, info};

// ─────────────────────────────────────────────────────────────────────────────
// Codec
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Codec {
    H264,
    H265,
    Unknown,
}

impl std::fmt::Display for Codec {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Codec::H264    => write!(f, "H264"),
            Codec::H265    => write!(f, "H265"),
            Codec::Unknown => write!(f, "Unknown"),
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// RTP header
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct RtpHeader {
    pub pt:             u8,
    pub seq:            u16,
    pub ts:             u32,
    pub ssrc:           u32,
    pub marker:         bool,
    pub payload_offset: usize,
}

/// Parse an RTP header from a raw byte slice.
/// Returns None if the data is too short or the version field is wrong.
pub fn parse_rtp_header(data: &[u8]) -> Option<RtpHeader> {
    if data.len() < 12 {
        return None;
    }
    if (data[0] >> 6) != 2 {   // version must be 2
        return None;
    }

    let flags   = data[0];
    let pt_byte = data[1];
    let seq     = u16::from_be_bytes([data[2], data[3]]);
    let ts      = u32::from_be_bytes([data[4], data[5], data[6], data[7]]);
    let ssrc    = u32::from_be_bytes([data[8], data[9], data[10], data[11]]);
    let marker  = (pt_byte & 0x80) != 0;
    let pt      = pt_byte & 0x7F;
    let cc      = (flags & 0x0F) as usize;   // CSRC count
    let has_ext = (flags & 0x10) != 0;

    let mut payload_offset = 12 + cc * 4;

    if has_ext {
        if data.len() < payload_offset + 4 {
            return None;
        }
        let ext_len =
            u16::from_be_bytes([data[payload_offset + 2], data[payload_offset + 3]]) as usize;
        payload_offset += 4 + ext_len * 4;
    }

    if payload_offset > data.len() {
        return None;
    }

    Some(RtpHeader { pt, seq, ts, ssrc, marker, payload_offset })
}

/// Rewrite RTP seq, timestamp and optionally SSRC in-place on a cloned buffer.
pub fn rtp_rewrite(payload: &[u8], new_seq: u16, new_ts: u32, new_ssrc: Option<u32>) -> Vec<u8> {
    if payload.len() < 12 {
        return payload.to_vec();
    }
    let mut out = payload.to_vec();
    let ssrc = new_ssrc.unwrap_or_else(|| u32::from_be_bytes([out[8], out[9], out[10], out[11]]));

    out[2..4].copy_from_slice(&new_seq.to_be_bytes());
    out[4..8].copy_from_slice(&new_ts.to_be_bytes());
    out[8..12].copy_from_slice(&ssrc.to_be_bytes());
    out
}

/// Build a 4-byte RTSP interleaved header + payload.
#[inline]
pub fn build_interleaved(channel: u8, payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + payload.len());
    out.push(0x24);
    out.push(channel);
    out.extend_from_slice(&(payload.len() as u16).to_be_bytes());
    out.extend_from_slice(payload);
    out
}

// ─────────────────────────────────────────────────────────────────────────────
// Codec detection from NAL units
// ─────────────────────────────────────────────────────────────────────────────

fn detect_codec(payload: &[u8]) -> Option<Codec> {
    if payload.len() < 2 {
        return None;
    }
    let nal_h264 = payload[0] & 0x1F;
    let nal_h265 = (payload[0] >> 1) & 0x3F;

    const H264_NAL: &[u8] = &[1, 5, 6, 7, 8, 24, 28];
    const H265_NAL: &[u8] = &[19, 20, 32, 33, 34, 39, 49];

    if H264_NAL.contains(&nal_h264) { return Some(Codec::H264); }
    if H265_NAL.contains(&nal_h265) { return Some(Codec::H265); }

    // FU-A H264 (type 28)
    if nal_h264 == 28 {
        let fu = payload[1] & 0x1F;
        if H264_NAL.contains(&fu) { return Some(Codec::H264); }
    }
    // FU H265 (type 49)
    if nal_h265 == 49 && payload.len() >= 3 {
        let fu = payload[2] & 0x3F;
        if H265_NAL.contains(&fu) { return Some(Codec::H265); }
    }
    None
}

// ─────────────────────────────────────────────────────────────────────────────
// StreamParams — result of the probe
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct StreamParams {
    pub pt:           u8,
    pub ssrc:         u32,
    pub channel:      u8,
    pub codec:        Codec,
    pub fps:          f64,
    pub total_frames: usize,
    pub gaps:         usize,
}

impl StreamParams {
    pub fn ssrc_hex(&self) -> String {
        format!("0x{:08x}", self.ssrc)
    }

    pub fn ts_per_frame(&self) -> u32 {
        (90000.0 / self.fps.max(1.0)) as u32
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// RTPProbe
// ─────────────────────────────────────────────────────────────────────────────

pub struct RTPProbe {
    probe_duration: Duration,
    min_frames:     usize,
    start:          Instant,

    pt_counts:      HashMap<u8,  usize>,
    ssrc_counts:    HashMap<u32, usize>,
    channel_counts: HashMap<u8,  usize>,
    codec_votes:    HashMap<Codec, usize>,

    /// (elapsed_secs, rtp_ts) pairs — used for FPS estimation
    timestamps:  Vec<(f64, u32)>,
    last_seq:    Option<u16>,
    gaps:        usize,
    total_frames: usize,

    result: Option<StreamParams>,
}

impl RTPProbe {
    pub fn new(probe_duration: Duration, min_frames: usize) -> Self {
        Self {
            probe_duration,
            min_frames,
            start: Instant::now(),
            pt_counts:      HashMap::new(),
            ssrc_counts:    HashMap::new(),
            channel_counts: HashMap::new(),
            codec_votes:    HashMap::new(),
            timestamps:     Vec::with_capacity(512),
            last_seq:       None,
            gaps:           0,
            total_frames:   0,
            result:         None,
        }
    }

    /// Feed one interleaved RTP frame.
    /// Returns true the instant the probe transitions to ready.
    pub fn feed(&mut self, channel: u8, rtp_payload: &[u8]) -> bool {
        let hdr = match parse_rtp_header(rtp_payload) {
            Some(h) => h,
            None    => return false,
        };

        let now = self.start.elapsed().as_secs_f64();
        self.total_frames += 1;

        *self.channel_counts.entry(channel).or_insert(0) += 1;
        *self.pt_counts.entry(hdr.pt).or_insert(0)       += 1;
        *self.ssrc_counts.entry(hdr.ssrc).or_insert(0)   += 1;
        self.timestamps.push((now, hdr.ts));

        // Gap detection
        if let Some(last) = self.last_seq {
            if hdr.seq != last.wrapping_add(1) {
                self.gaps += 1;
            }
        }
        self.last_seq = Some(hdr.seq);

        // Codec detection
        let payload_data = &rtp_payload[hdr.payload_offset..];
        if let Some(codec) = detect_codec(payload_data) {
            *self.codec_votes.entry(codec).or_insert(0) += 1;
        }

        // SPS H264 detection (type 7)
        if !payload_data.is_empty() && (payload_data[0] & 0x1F) == 7 && payload_data.len() >= 4 {
            debug!("[SPS H264] profile_idc={} level={}", payload_data[1], payload_data[3]);
        }

        if self.result.is_some() {
            return false;   // already done, keep feeding for timestamp accuracy
        }

        let elapsed = self.start.elapsed();
        if elapsed >= self.probe_duration && self.total_frames >= self.min_frames {
            self.result = Some(self.compute());
            self.print_result();
            return true;    // just became ready
        }
        false
    }

    pub fn ready(&self) -> bool {
        self.result.is_some()
    }

    pub fn params(&self) -> Option<&StreamParams> {
        self.result.as_ref()
    }

    /// Force completion even if time/frame thresholds haven't been met.
    pub fn force_result(&mut self) -> &StreamParams {
        if self.result.is_none() {
            self.result = Some(self.compute());
            self.print_result();
        }
        self.result.as_ref().unwrap()
    }

    // ── internals ─────────────────────────────────────────────────────────

    fn compute(&self) -> StreamParams {
        let pt = self.pt_counts.iter()
            .max_by_key(|(_, v)| *v)
            .map(|(k, _)| *k)
            .unwrap_or(96);

        let ssrc = self.ssrc_counts.iter()
            .max_by_key(|(_, v)| *v)
            .map(|(k, _)| *k)
            .unwrap_or(0);

        let channel = self.channel_counts.iter()
            .max_by_key(|(_, v)| *v)
            .map(|(k, _)| *k)
            .unwrap_or(0);

        let codec = self.codec_votes.iter()
            .max_by_key(|(_, v)| *v)
            .map(|(k, _)| k.clone())
            .unwrap_or(Codec::H264);

        let fps = self.estimate_fps().unwrap_or(25.0);

        StreamParams { pt, ssrc, channel, codec, fps,
                       total_frames: self.total_frames, gaps: self.gaps }
    }

    fn estimate_fps(&self) -> Option<f64> {
        if self.timestamps.len() < 10 {
            return None;
        }
        let samples = {
            let n = self.timestamps.len();
            if n > 60 { &self.timestamps[n - 60..] } else { &self.timestamps[..] }
        };

        const CLOCK: f64 = 90_000.0;
        let mut fps_samples: Vec<f64> = Vec::with_capacity(samples.len());

        for w in samples.windows(2) {
            let wall_dt = w[1].0 - w[0].0;
            let rtp_dt  = w[1].1.wrapping_sub(w[0].1) as f64;

            if rtp_dt == 0.0 || rtp_dt > CLOCK || wall_dt < 0.0001 { continue; }
            let fps = CLOCK / rtp_dt;
            if (1.0..=120.0).contains(&fps) { fps_samples.push(fps); }
        }

        if fps_samples.is_empty() { return None; }

        fps_samples.sort_by(|a, b| a.total_cmp(b));
        let mid = fps_samples.len() / 2;
        Some((fps_samples[mid] * 100.0).round() / 100.0)
    }

    fn print_result(&self) {
        if let Some(r) = &self.result {
            info!("═══════════════════════════════════════════════════════");
            info!("  RTPProbe — parámetros detectados automáticamente");
            info!("═══════════════════════════════════════════════════════");
            info!("  PT (Payload Type) : {}", r.pt);
            info!("  SSRC              : {}", r.ssrc_hex());
            info!("  Canal interleaved : {}", r.channel);
            info!("  Codec detectado   : {}", r.codec);
            info!("  FPS estimado      : {:.2}", r.fps);
            info!("  Frames analizados : {}  (gaps: {})", r.total_frames, r.gaps);
            info!("═══════════════════════════════════════════════════════");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rtp_header_bytes(pt: u8, seq: u16, ts: u32, ssrc: u32, marker: bool) -> Vec<u8> {
        let mut v = vec![0x80u8]; // V=2, P=0, X=0, CC=0
        v.push(if marker { pt | 0x80 } else { pt & 0x7F });
        v.extend_from_slice(&seq.to_be_bytes());
        v.extend_from_slice(&ts.to_be_bytes());
        v.extend_from_slice(&ssrc.to_be_bytes());
        v
    }

    #[test]
    fn parse_rtp_header_extracts_fields() {
        let mut pkt = rtp_header_bytes(96, 1234, 90000, 0xDEADBEEF, true);
        pkt.extend_from_slice(b"payload");
        let hdr = parse_rtp_header(&pkt).expect("should parse");
        assert_eq!(hdr.pt, 96);
        assert_eq!(hdr.seq, 1234);
        assert_eq!(hdr.ts, 90000);
        assert_eq!(hdr.ssrc, 0xDEADBEEF);
        assert!(hdr.marker);
        assert_eq!(hdr.payload_offset, 12);
    }

    #[test]
    fn parse_rtp_header_rejects_too_short() {
        assert!(parse_rtp_header(&[0x80, 96, 0, 0]).is_none());
    }

    #[test]
    fn parse_rtp_header_rejects_wrong_version() {
        let mut pkt = rtp_header_bytes(96, 1, 1, 1, false);
        pkt[0] = 0x00; // version 0, not RTP's version 2
        assert!(parse_rtp_header(&pkt).is_none());
    }

    #[test]
    fn parse_rtp_header_accounts_for_csrc_count() {
        let mut pkt = vec![0x82u8, 96]; // CC=2
        pkt.extend_from_slice(&1u16.to_be_bytes());
        pkt.extend_from_slice(&2u32.to_be_bytes());
        pkt.extend_from_slice(&3u32.to_be_bytes());
        pkt.extend_from_slice(&[0u8; 8]); // 2 CSRC identifiers, 4 bytes each
        pkt.extend_from_slice(b"data");
        let hdr = parse_rtp_header(&pkt).expect("should parse");
        assert_eq!(hdr.payload_offset, 12 + 2 * 4);
    }

    #[test]
    fn rtp_rewrite_overwrites_seq_ts_ssrc_and_keeps_payload() {
        let mut pkt = rtp_header_bytes(96, 1, 1, 0x11111111, false);
        pkt.extend_from_slice(b"XYZ");
        let out = rtp_rewrite(&pkt, 42, 900_000, Some(0x22222222));
        let hdr = parse_rtp_header(&out).unwrap();
        assert_eq!(hdr.seq, 42);
        assert_eq!(hdr.ts, 900_000);
        assert_eq!(hdr.ssrc, 0x22222222);
        assert_eq!(&out[12..], b"XYZ");
    }

    #[test]
    fn rtp_rewrite_keeps_original_ssrc_when_none() {
        let pkt = rtp_header_bytes(96, 1, 1, 0xABCDEF01, false);
        let out = rtp_rewrite(&pkt, 5, 5, None);
        assert_eq!(parse_rtp_header(&out).unwrap().ssrc, 0xABCDEF01);
    }

    #[test]
    fn build_interleaved_produces_correct_wire_format() {
        let wire = build_interleaved(7, b"hello");
        assert_eq!(wire[0], 0x24);
        assert_eq!(wire[1], 7);
        assert_eq!(u16::from_be_bytes([wire[2], wire[3]]), 5);
        assert_eq!(&wire[4..], b"hello");
    }

    #[test]
    fn probe_becomes_ready_and_picks_majority_pt_ssrc_channel() {
        let mut probe = RTPProbe::new(Duration::from_millis(1), 5);
        std::thread::sleep(Duration::from_millis(5));

        let mut became_ready = false;
        for i in 0..10u16 {
            let pkt = rtp_header_bytes(96, i, (i as u32) * 3600, 0xCAFEBABE, false);
            if probe.feed(0, &pkt) {
                became_ready = true;
            }
        }
        assert!(became_ready, "probe should have transitioned to ready");
        let params = probe.params().expect("should have params once ready");
        assert_eq!(params.pt, 96);
        assert_eq!(params.ssrc, 0xCAFEBABE);
        assert_eq!(params.channel, 0);
    }

    #[test]
    fn probe_estimates_fps_from_timestamp_deltas() {
        let mut probe = RTPProbe::new(Duration::from_millis(1), 15);
        std::thread::sleep(Duration::from_millis(5));
        // 3600 ticks/frame at the 90kHz RTP clock => 25fps. A real (if tiny) sleep
        // between frames matters here: estimate_fps() filters out samples whose
        // wall-clock gap is under 100us, so a tight zero-delay loop would starve it.
        for i in 0..20u16 {
            let pkt = rtp_header_bytes(96, i, (i as u32) * 3600, 0xAAAA, false);
            probe.feed(0, &pkt);
            std::thread::sleep(Duration::from_micros(500));
        }
        let params = probe.force_result();
        assert!((params.fps - 25.0).abs() < 0.5, "expected ~25fps, got {}", params.fps);
    }

    #[test]
    fn probe_detects_sequence_gaps() {
        let mut probe = RTPProbe::new(Duration::from_secs(999), 999); // never auto-completes
        probe.feed(0, &rtp_header_bytes(96, 1, 0, 1, false));
        probe.feed(0, &rtp_header_bytes(96, 2, 3600, 1, false));
        probe.feed(0, &rtp_header_bytes(96, 10, 7200, 1, false)); // jump = one gap
        let params = probe.force_result();
        assert_eq!(params.gaps, 1);
    }
}
