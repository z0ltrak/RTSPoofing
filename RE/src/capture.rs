//! capture.rs — Capture file I/O (.rtp binary format).
//!
//! File format (repeated records):
//!   4B  big-endian u32  →  total record length (= 2 + 2 + len(rtp_payload))
//!   1B  interleaved channel
//!   1B  reserved = 0
//!   2B  big-endian u16  →  len(rtp_payload)
//!   NB  rtp_payload

//! capture.rs — Capture file I/O (.rtp binary format).

use std::io::Write;
use std::path::Path;
use anyhow::{Context, Result};
use tracing::{info, warn};

use crate::rtp_probe::parse_rtp_header;

pub const RECORD_HEADER_SIZE: usize = 8;

#[derive(Clone)]
pub struct CapturedFrame {
    pub channel: u8,
    pub payload: Vec<u8>,
}

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

#[inline]
pub fn write_frame<W: Write>(w: &mut W, channel: u8, rtp_payload: &[u8]) -> Result<()> {
    let rtp_len  = rtp_payload.len() as u16;
    let total_len = 4u32 + rtp_len as u32;   // sin paréntesis innecesarios

    let mut hdr = [0u8; 8];
    hdr[0..4].copy_from_slice(&total_len.to_be_bytes());
    hdr[4] = channel;
    hdr[5] = 0;
    hdr[6..8].copy_from_slice(&rtp_len.to_be_bytes());

    w.write_all(&hdr)?;
    w.write_all(rtp_payload)?;
    Ok(())
}

pub fn read_capture_file(path: &Path) -> Result<(Vec<CapturedFrame>, CaptureParams)> {
    let data = std::fs::read(path)
        .with_context(|| format!("Cannot read capture file: {}", path.display()))?;

    let mut frames: Vec<CapturedFrame> = Vec::new();
    let mut params = CaptureParams::default();
    let mut offset = 0usize;
    let mut first  = true;

    while offset + RECORD_HEADER_SIZE <= data.len() {
        let _total_len = u32::from_be_bytes(data[offset..offset+4].try_into().unwrap()) as usize;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn sample_rtp(seq: u16, ts: u32, ssrc: u32) -> Vec<u8> {
        let mut v = vec![0x80u8, 96]; // V=2, PT=96 (H264)
        v.extend_from_slice(&seq.to_be_bytes());
        v.extend_from_slice(&ts.to_be_bytes());
        v.extend_from_slice(&ssrc.to_be_bytes());
        v.extend_from_slice(b"payload-data");
        v
    }

    #[test]
    fn write_frame_produces_correct_header() {
        let mut buf = Cursor::new(Vec::new());
        let payload = b"hello world";
        write_frame(&mut buf, 3, payload).unwrap();
        let data = buf.into_inner();

        let total_len = u32::from_be_bytes(data[0..4].try_into().unwrap());
        assert_eq!(total_len, 4 + payload.len() as u32);
        assert_eq!(data[4], 3, "channel");
        assert_eq!(data[5], 0, "reserved byte must be zero");
        let rtp_len = u16::from_be_bytes(data[6..8].try_into().unwrap());
        assert_eq!(rtp_len as usize, payload.len());
        assert_eq!(&data[8..], payload);
    }

    #[test]
    fn round_trip_through_a_real_file() {
        let path = std::env::temp_dir().join(format!(
            "rtspoofing_test_{}_{}.rtp",
            std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos(),
        ));

        let frames_in = [
            sample_rtp(0, 0, 0xC0FFEE01),
            sample_rtp(1, 3600, 0xC0FFEE01),
            sample_rtp(2, 7200, 0xC0FFEE01),
        ];

        {
            let mut f = std::fs::File::create(&path).unwrap();
            for (i, rtp) in frames_in.iter().enumerate() {
                write_frame(&mut f, (i % 2) as u8, rtp).unwrap();
            }
        }

        let result = read_capture_file(&path);
        std::fs::remove_file(&path).ok();
        let (frames_out, params) = result.unwrap();

        assert_eq!(frames_out.len(), 3);
        for (i, f) in frames_out.iter().enumerate() {
            assert_eq!(f.channel, (i % 2) as u8);
            assert_eq!(f.payload, frames_in[i]);
        }

        assert_eq!(params.pt, 96);
        assert_eq!(params.ssrc, 0xC0FFEE01);
        assert_eq!(params.codec_name, "H264");
        assert!(params.fps > 0.0, "should estimate a positive fps from the timestamps");
    }

    #[test]
    fn read_capture_file_missing_path_errors_instead_of_panicking() {
        let path = std::env::temp_dir().join("rtspoofing_definitely_does_not_exist.rtp");
        assert!(read_capture_file(&path).is_err());
    }
}
