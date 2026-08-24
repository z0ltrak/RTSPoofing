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
                    // No interleaved frame ahead — flush all as text.
                    // mem::take swaps the buffer out instead of draining/copying it.
                    out.push(ParsedChunk::Text(std::mem::take(&mut self.buf)));
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
                    if !(8..=MAX_FRAME).contains(&length) {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn frame_bytes(channel: u8, payload: &[u8]) -> Vec<u8> {
        let mut v = vec![0x24, channel];
        v.extend_from_slice(&(payload.len() as u16).to_be_bytes());
        v.extend_from_slice(payload);
        v
    }

    #[test]
    fn plain_text_with_no_dollar_is_forwarded_as_text() {
        let mut p = InterleavedParser::new();
        let chunks = p.feed(b"SETUP rtsp://x RTSP/1.0\r\n\r\n");
        assert_eq!(chunks.len(), 1);
        match &chunks[0] {
            ParsedChunk::Text(t) => assert_eq!(t, b"SETUP rtsp://x RTSP/1.0\r\n\r\n"),
            _ => panic!("expected Text"),
        }
    }

    #[test]
    fn single_complete_frame_in_one_feed() {
        let mut p = InterleavedParser::new();
        let payload = vec![0xAAu8; 20];
        let wire = frame_bytes(3, &payload);
        let chunks = p.feed(&wire);
        assert_eq!(chunks.len(), 1);
        match &chunks[0] {
            ParsedChunk::Frame(ch, pl) => {
                assert_eq!(*ch, 3);
                assert_eq!(pl, &payload);
            }
            _ => panic!("expected Frame"),
        }
    }

    #[test]
    fn frame_split_across_multiple_feeds_reassembles() {
        let mut p = InterleavedParser::new();
        let payload = vec![0xBBu8; 30];
        let wire = frame_bytes(1, &payload);

        let chunks1 = p.feed(&wire[..4]); // just the header
        assert!(chunks1.is_empty(), "should wait for more data");

        let chunks2 = p.feed(&wire[4..14]); // partial payload
        assert!(chunks2.is_empty(), "still incomplete");

        let chunks3 = p.feed(&wire[14..]); // rest of the payload
        assert_eq!(chunks3.len(), 1);
        match &chunks3[0] {
            ParsedChunk::Frame(ch, pl) => {
                assert_eq!(*ch, 1);
                assert_eq!(pl, &payload);
            }
            _ => panic!("expected Frame"),
        }
    }

    #[test]
    fn text_before_a_frame_is_split_out() {
        let mut p = InterleavedParser::new();
        let payload = vec![0xCCu8; 12];
        let mut wire = b"200 OK\r\n\r\n".to_vec();
        wire.extend_from_slice(&frame_bytes(0, &payload));

        let chunks = p.feed(&wire);
        assert_eq!(chunks.len(), 2);
        match &chunks[0] {
            ParsedChunk::Text(t) => assert_eq!(t, b"200 OK\r\n\r\n"),
            _ => panic!("expected Text first"),
        }
        match &chunks[1] {
            ParsedChunk::Frame(ch, pl) => {
                assert_eq!(*ch, 0);
                assert_eq!(pl, &payload);
            }
            _ => panic!("expected Frame second"),
        }
    }

    #[test]
    fn false_dollar_below_minimum_length_is_never_parsed_as_a_frame() {
        // length field = 7, below the 8-byte sanity minimum for a real RTP frame.
        let mut p = InterleavedParser::new();
        let mut wire = vec![0x24, 0, 0, 7];
        wire.extend_from_slice(b"1234567");
        let chunks = p.feed(&wire);
        for c in chunks {
            assert!(
                matches!(c, ParsedChunk::Text(_)),
                "a length below the 8-byte minimum must never be parsed as a real frame"
            );
        }
    }
}
