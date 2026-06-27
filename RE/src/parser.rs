//! parser.rs — Stateful RTSP interleaved stream parser.
//!
//! Equivalent of InterleavedParser in RTSPoofing.py.
//! Parses raw TCP bytes and splits them into:
//!   - Interleaved RTP frames  ($CH LEN payload)
//!   - RTSP text (everything else)

const MAX_FRAME: usize = 1 << 18;   // 256 KiB sanity cap

pub enum ParsedChunk {
    /// A complete interleaved RTP frame: (channel, payload)
    Frame(u8, Vec<u8>),
    /// Raw RTSP text bytes
    Text(Vec<u8>),
}

pub struct InterleavedParser {
    buf: Vec<u8>,
}

impl InterleavedParser {
    pub fn new() -> Self {
        Self { buf: Vec::with_capacity(16 * 1024) }
    }

    /// Feed raw TCP bytes. Returns all complete chunks parsed so far.
    pub fn feed(&mut self, data: &[u8]) -> Vec<ParsedChunk> {
        self.buf.extend_from_slice(data);
        self.drain()
    }

    fn drain(&mut self) -> Vec<ParsedChunk> {
        let mut out = Vec::new();

        loop {
            if self.buf.is_empty() {
                break;
            }

            // Find the next '$' marker
            match self.buf.iter().position(|&b| b == b'$') {
                None => {
                    // No interleaved frame ahead — flush all as text
                    out.push(ParsedChunk::Text(self.buf.drain(..).collect()));
                    break;
                }
                Some(0) => {
                    // '$' is at the front
                    if self.buf.len() < 4 {
                        break;   // need more data for the header
                    }
                    let channel = self.buf[1];
                    let length  = u16::from_be_bytes([self.buf[2], self.buf[3]]) as usize;

                    // Sanity check: valid RTP frames are at least 12 bytes
                    if length < 8 || length > MAX_FRAME {
                        // False '$', skip it and emit as text
                        out.push(ParsedChunk::Text(self.buf.drain(..1).collect()));
                        continue;
                    }

                    if self.buf.len() < 4 + length {
                        break;   // incomplete frame, wait for more data
                    }

                    let payload: Vec<u8> = self.buf[4..4 + length].to_vec();
                    self.buf.drain(..4 + length);
                    out.push(ParsedChunk::Frame(channel, payload));
                }
                Some(idx) => {
                    // Text before the '$' — emit it
                    let text: Vec<u8> = self.buf.drain(..idx).collect();
                    out.push(ParsedChunk::Text(text));
                    // Loop again; '$' is now at position 0
                }
            }
        }

        out
    }
}
