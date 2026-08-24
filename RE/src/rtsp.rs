//! rtsp.rs — Lightweight RTSP message scanning and SETUP Transport-header rewriting.
//!
//! Used to detect and rewrite SETUP requests/responses so UDP-transport media
//! sessions route their RTP/RTCP through proxy-owned sockets instead of flowing
//! directly between camera and NVR. Deliberately not a full RFC 2326 parser —
//! see the "Pragmatic RTSP parsing" scope note in the project plan: we only need
//! to reliably find message boundaries and pull out CSeq/Transport, not handle
//! every RTSP method or header.

const MAX_RTSP_MSG: usize = 32 * 1024;

/// Accumulates raw RTSP text bytes and emits complete messages (header block
/// plus any Content-Length body) as they become available. Mirrors
/// `InterleavedParser`'s accumulate-then-scan style, but for RTSP message
/// boundaries instead of `$`-framed binary chunks.
pub struct RtspTextScanner {
    buf: Vec<u8>,
}

impl RtspTextScanner {
    pub fn new() -> Self {
        Self { buf: Vec::with_capacity(4096) }
    }

    /// Feed raw bytes, get back zero or more complete message blobs.
    pub fn feed(&mut self, data: &[u8]) -> Vec<Vec<u8>> {
        self.buf.extend_from_slice(data);
        let mut out = Vec::new();

        loop {
            let header_end = match find_double_crlf(&self.buf) {
                Some(i) => i,
                None => {
                    if self.buf.len() > MAX_RTSP_MSG {
                        // Doesn't look like it'll ever complete — flush it as-is
                        // rather than buffering unboundedly or blackholing traffic.
                        out.push(std::mem::take(&mut self.buf));
                    }
                    break;
                }
            };

            let content_length = parse_content_length(&self.buf[..header_end]);
            let total_len = header_end + 4 + content_length;

            if self.buf.len() < total_len {
                if total_len > MAX_RTSP_MSG {
                    out.push(std::mem::take(&mut self.buf));
                }
                break;
            }

            out.push(self.buf.drain(..total_len).collect());
        }

        out
    }
}

fn find_double_crlf(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

fn parse_content_length(header_bytes: &[u8]) -> usize {
    let text = String::from_utf8_lossy(header_bytes);
    for line in text.lines() {
        if let Some(v) = line.strip_prefix("Content-Length:").or_else(|| line.strip_prefix("Content-length:")) {
            if let Ok(n) = v.trim().parse::<usize>() {
                return n;
            }
        }
    }
    0
}

// ─────────────────────────────────────────────────────────────────────────────
// SETUP request/response parsing
// ─────────────────────────────────────────────────────────────────────────────

pub struct SetupRequest {
    pub cseq: String,
    pub client_port: (u16, u16),
}

pub struct SetupResponse {
    pub cseq: String,
    pub server_port: (u16, u16),
}

/// Parse a SETUP request for a UDP (non-interleaved) Transport header.
/// Returns None if this isn't a SETUP request, or its Transport is TCP-interleaved.
pub fn parse_setup_request(msg: &str) -> Option<SetupRequest> {
    if !msg.lines().next()?.starts_with("SETUP ") {
        return None;
    }
    let cseq = find_header(msg, "CSeq")?;
    let transport = find_header(msg, "Transport")?;
    if transport.contains("interleaved=") {
        return None;
    }
    let client_port = parse_port_pair(&transport, "client_port=")?;
    Some(SetupRequest { cseq, client_port })
}

/// Parse a SETUP response (matched against a pending CSeq by the caller).
pub fn parse_setup_response(msg: &str) -> Option<SetupResponse> {
    let status_line = msg.lines().next()?;
    if !status_line.starts_with("RTSP/1.0 2") {
        return None; // not a 2xx response
    }
    let cseq = find_header(msg, "CSeq")?;
    let transport = find_header(msg, "Transport")?;
    let server_port = parse_port_pair(&transport, "server_port=")?;
    Some(SetupResponse { cseq, server_port })
}

/// Search only the header block (up to the first blank line) so a header-like
/// string inside a response body (e.g. an SDP payload) can never be mistaken
/// for an actual RTSP header.
fn find_header(msg: &str, name: &str) -> Option<String> {
    let prefix = format!("{}:", name);
    for line in msg.lines().take_while(|l| !l.is_empty()) {
        if line.len() >= prefix.len() && line[..prefix.len()].eq_ignore_ascii_case(&prefix) {
            return Some(line[prefix.len()..].trim().to_string());
        }
    }
    None
}

fn parse_port_pair(transport: &str, key: &str) -> Option<(u16, u16)> {
    for part in transport.split(';') {
        let part = part.trim();
        if let Some(v) = part.strip_prefix(key) {
            let mut it = v.splitn(2, '-');
            let a: u16 = it.next()?.trim().parse().ok()?;
            let b: u16 = it.next().unwrap_or("").trim().parse().unwrap_or(a + 1);
            return Some((a, b));
        }
    }
    None
}

/// Replace `key<a>-<b>` inside `msg` with `key<new.0>-<new.1>`, leaving
/// everything else — including any body — byte-for-byte identical. A message
/// with no body (true for every SETUP request/response in practice) has no
/// Content-Length to keep in sync, so changing the substituted value's length
/// is safe; message framing here is by blank-line/Content-Length, not a
/// separate length prefix.
pub fn rewrite_port_pair(msg: &str, key: &str, new_ports: (u16, u16)) -> String {
    let Some(idx) = msg.find(key) else { return msg.to_string() };
    let start = idx + key.len();
    let rest = &msg[start..];
    let end_offset = rest.find(|c: char| c != '-' && !c.is_ascii_digit()).unwrap_or(rest.len());

    let mut out = String::with_capacity(msg.len() + 8);
    out.push_str(&msg[..start]);
    out.push_str(&format!("{}-{}", new_ports.0, new_ports.1));
    out.push_str(&rest[end_offset..]);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup_request(cseq: &str, client_port: &str) -> String {
        format!(
            "SETUP rtsp://192.168.1.10/track1 RTSP/1.0\r\nCSeq: {cseq}\r\n\
             Transport: RTP/AVP;unicast;client_port={client_port}\r\n\r\n"
        )
    }

    #[test]
    fn parses_udp_setup_request() {
        let msg = setup_request("2", "8000-8001");
        let req = parse_setup_request(&msg).expect("should parse");
        assert_eq!(req.cseq, "2");
        assert_eq!(req.client_port, (8000, 8001));
    }

    #[test]
    fn rejects_tcp_interleaved_setup_request() {
        let msg = "SETUP rtsp://x/track1 RTSP/1.0\r\nCSeq: 1\r\n\
                   Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n\r\n";
        assert!(parse_setup_request(msg).is_none());
    }

    #[test]
    fn rejects_non_setup_requests() {
        let play = "PLAY rtsp://x/track1 RTSP/1.0\r\nCSeq: 3\r\n\r\n";
        assert!(parse_setup_request(play).is_none());
        let describe = "DESCRIBE rtsp://x RTSP/1.0\r\nCSeq: 1\r\n\r\n";
        assert!(parse_setup_request(describe).is_none());
    }

    #[test]
    fn parses_setup_response() {
        let msg = "RTSP/1.0 200 OK\r\nCSeq: 2\r\n\
                   Transport: RTP/AVP;unicast;client_port=8000-8001;server_port=9000-9001\r\n\r\n";
        let resp = parse_setup_response(msg).expect("should parse");
        assert_eq!(resp.cseq, "2");
        assert_eq!(resp.server_port, (9000, 9001));
    }

    #[test]
    fn rejects_non_2xx_setup_response() {
        let msg = "RTSP/1.0 461 Unsupported Transport\r\nCSeq: 2\r\n\r\n";
        assert!(parse_setup_response(msg).is_none());
    }

    #[test]
    fn rewrite_port_pair_substitutes_only_that_field() {
        let msg = "Transport: RTP/AVP;unicast;client_port=8000-8001;mode=play\r\n";
        let out = rewrite_port_pair(msg, "client_port=", (54321, 54322));
        assert_eq!(out, "Transport: RTP/AVP;unicast;client_port=54321-54322;mode=play\r\n");
    }

    #[test]
    fn rewrite_port_pair_handles_different_digit_counts() {
        // 4-digit -> 5-digit ports must not corrupt whatever follows.
        let msg = "client_port=8000-8001;next=1\r\n";
        let out = rewrite_port_pair(msg, "client_port=", (60123, 60124));
        assert_eq!(out, "client_port=60123-60124;next=1\r\n");
    }

    #[test]
    fn rewrite_port_pair_leaves_message_unchanged_if_key_absent() {
        let msg = "Transport: RTP/AVP/TCP;interleaved=0-1\r\n";
        let out = rewrite_port_pair(msg, "client_port=", (1, 2));
        assert_eq!(out, msg);
    }

    #[test]
    fn scanner_yields_one_message_fed_all_at_once() {
        let mut scanner = RtspTextScanner::new();
        let msg = setup_request("1", "1000-1001");
        let out = scanner.feed(msg.as_bytes());
        assert_eq!(out.len(), 1);
        assert_eq!(out[0], msg.as_bytes());
    }

    #[test]
    fn scanner_reassembles_a_message_split_across_feeds() {
        let mut scanner = RtspTextScanner::new();
        let msg = setup_request("1", "1000-1001");
        let bytes = msg.as_bytes();
        let mid = bytes.len() / 2;

        let out1 = scanner.feed(&bytes[..mid]);
        assert!(out1.is_empty(), "message isn't complete yet");

        let out2 = scanner.feed(&bytes[mid..]);
        assert_eq!(out2.len(), 1);
        assert_eq!(out2[0], bytes);
    }

    #[test]
    fn scanner_waits_for_full_content_length_body() {
        let mut scanner = RtspTextScanner::new();
        let body = "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n";
        let msg = format!(
            "RTSP/1.0 200 OK\r\nCSeq: 1\r\nContent-Length: {}\r\n\r\n{}",
            body.len(), body
        );
        let bytes = msg.as_bytes();
        let header_end = bytes.len() - body.len();

        let out1 = scanner.feed(&bytes[..header_end]);
        assert!(out1.is_empty(), "should wait for the Content-Length body before emitting");

        let out2 = scanner.feed(&bytes[header_end..]);
        assert_eq!(out2.len(), 1);
        assert_eq!(out2[0], bytes);
    }

    #[test]
    fn scanner_handles_back_to_back_messages_in_one_feed() {
        let mut scanner = RtspTextScanner::new();
        let msg1 = setup_request("1", "1000-1001");
        let msg2 = setup_request("2", "2000-2001");
        let combined = format!("{msg1}{msg2}");
        let out = scanner.feed(combined.as_bytes());
        assert_eq!(out.len(), 2);
        assert_eq!(out[0], msg1.as_bytes());
        assert_eq!(out[1], msg2.as_bytes());
    }

    #[test]
    fn scanner_flushes_oversized_unterminated_buffer_instead_of_growing_forever() {
        let mut scanner = RtspTextScanner::new();
        let junk = vec![b'A'; MAX_RTSP_MSG + 100]; // no \r\n\r\n anywhere
        let out = scanner.feed(&junk);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].len(), junk.len());
    }
}
