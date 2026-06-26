//! capture.rs — Capture file I/O (.rtp binary format).
//!
//! File format (repeated records):
//!   4B  big-endian u32  →  total record length (= 2 + 2 + len(rtp_payload))
//!   1B  interleaved channel
//!   1B  reserved = 0
//!   2B  big-endian u16  →  len(rtp_payload)
//!   NB  rtp_payload

use std::io::Write;
use std::path::Path;
use anyhow::{Context, Result};
use tracing::{info, warn};

use crate::rtp_probe::parse_rtp_header;

pub const RECORD_HEADER_SIZE: usize = 8; // u32 + u8 + u8 + u16

/// A single captured frame.
#[derive(Clone)]
pub struct CapturedFrame {
    pub channel: u8,
    pub payload: Vec<u8>,
}

/// Parameters extracted from the capture file.
#[derive(Debug, Clone)]
pub struct CaptureParams {
    pub pt:         u8,
    pub ssrc:       u32,
    pub codec_name: String,
    pub fps:        f64,
}

impl Default for CaptureParams {
    fn default() -> Self {
        Self { pt: 96, ssrc: 0, codec_name: "Unknown".into(), fps: 25.0 }
    }
}

/// Write one interleaved frame to the capture file.
/// Uses a buffered writer — caller is responsible for flushing periodically.
#[inline]
pub fn write_frame<W: Write>(w: &mut W, channel: u8, rtp_payload: &[u8]) -> Result<()> {
    let rtp_len  = rtp_payload.len() as u16;
    let total_len = (4u32 + rtp_len as u32);   // channel(1) + reserved(1) + len(2) + payload

    let mut hdr = [0u8; 8];
    hdr[0..4].copy_from_slice(&total_len.to_be_bytes());
    hdr[4] = channel;
    hdr[5] = 0;   // reserved
    hdr[6..8].copy_from_slice(&rtp_len.to_be_bytes());

    w.write_all(&hdr)?;
    w.write_all(rtp_payload)?;
    Ok(())
}

/// Load all captured frames from a .rtp file.
pub fn read_capture_file(path: &Path) -> Result<(Vec<CapturedFrame>, CaptureParams)> {
    let data = std::fs::read(path)
        .with_context(|| format!("Cannot read capture file: {}", path.display()))?;

    let mut frames: Vec<CapturedFrame> = Vec::new();
    let mut params = CaptureParams::default();
    let mut offset = 0usize;
    let mut first  = true;

    while offset + RECORD_HEADER_SIZE <= data.len() {
        let total_len = u32::from_be_bytes(data[offset..offset+4].try_into().unwrap()) as usize;
        let channel   = data[offset + 4];
        let rtp_len   = u16::from_be_bytes(data[offset+6..offset+8].try_into().unwrap()) as usize;

        offset += RECORD_HEADER_SIZE;

        if offset + rtp_len > data.len() {
            warn!("Capture file truncated at frame {}", frames.len());
            break;
        }

        let payload = data[offset..offset + rtp_len].to_vec();
        offset += rtp_len;

        if first {
            if let Some(hdr) = parse_rtp_header(&payload) {
                params.pt   = hdr.pt;
                params.ssrc = hdr.ssrc;
                params.codec_name = match hdr.pt {
                    26        => "JPEG",
                    34        => "H263",
                    96 | 97   => "H264",
                    98 | 99   => "H265",
                    100       => "MPEG4",
                    _         => "Unknown",
                }.into();
            }
            first = false;
        }

        frames.push(CapturedFrame { channel, payload });
    }

    // FPS estimation from first and last RTP timestamps
    if frames.len() >= 2 {
        if let (Some(fh), Some(lh)) = (
            parse_rtp_header(&frames.first().unwrap().payload),
            parse_rtp_header(&frames.last().unwrap().payload),
        ) {
            if lh.ts > fh.ts {
                let duration = (lh.ts - fh.ts) as f64 / 90_000.0;
                if duration > 0.0 {
                    params.fps = frames.len() as f64 / duration;
                }
            }
        }
    }

    info!(
        "Loaded {} frames — PT={} SSRC=0x{:08X} FPS={:.1} Codec={}",
        frames.len(), params.pt, params.ssrc, params.fps, params.codec_name
    );

    Ok((frames, params))
}
