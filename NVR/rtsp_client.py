"""
Minimal RTSP 1.0 client (RFC 2326) for TCP-interleaved transport.

Scope: just enough RTSP to drive an IP camera at the application layer the
RTSPoofing PoC targets — OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, with Basic
and Digest (MD5) authentication, SDP parsing for a single video track, and
GET_PARAMETER-based keepalive. Everything else (ANNOUNCE, RECORD, SRTP, RTSP
2.0) is intentionally not here.

The read side exposes the raw socket after PLAY so the NVR orchestrator can
parse RTSP-interleaved frames itself.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


DEFAULT_RTSP_PORT = 554
DEFAULT_TIMEOUT_S = 10.0


@dataclass
class VideoTrack:
    """One m=video track from the SDP, enough to drive SETUP/PLAY."""

    control: str                 # the a=control: URL (absolute or relative)
    payload_type: int            # dynamic PT, usually 96/97
    encoding: str                # "H264" or "H265" / "HEVC"
    clock_rate: int = 90000
    sps: list[bytes] = field(default_factory=list)
    pps: list[bytes] = field(default_factory=list)
    vps: list[bytes] = field(default_factory=list)
    fmtp: dict[str, str] = field(default_factory=dict)
    rtp_channel: int = 0         # assigned during SETUP (interleaved=X-Y)
    rtcp_channel: int = 1


class RtspError(RuntimeError):
    pass


# ---------- SDP parsing ----------

def _b64_params(fmtp_params: dict[str, str], key: str) -> list[bytes]:
    raw = fmtp_params.get(key, "")
    out: list[bytes] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(base64.b64decode(chunk))
        except Exception:
            continue
    return out


def parse_sdp_video(sdp: str, base_url: str) -> Optional[VideoTrack]:
    """Return the first m=video track, or None if there isn't one."""
    lines = [ln.rstrip("\r") for ln in sdp.split("\n")]

    # Walk media sections, snapshotting attributes per section.
    sections: list[dict] = []
    current: Optional[dict] = None
    for ln in lines:
        if ln.startswith("m="):
            current = {"m": ln[2:], "attrs": []}
            sections.append(current)
        elif current is not None and ln.startswith("a="):
            current["attrs"].append(ln[2:])

    for sec in sections:
        if not sec["m"].startswith("video"):
            continue
        m_parts = sec["m"].split()
        if len(m_parts) < 4:
            continue
        try:
            pt = int(m_parts[3])
        except ValueError:
            continue

        track = VideoTrack(control=base_url, payload_type=pt, encoding="H264")
        for a in sec["attrs"]:
            if a.startswith("control:"):
                ctrl = a[len("control:"):].strip()
                if ctrl == "*" or ctrl == "":
                    track.control = base_url
                elif "://" in ctrl:
                    track.control = ctrl
                else:
                    sep = "" if base_url.endswith("/") or ctrl.startswith("/") else "/"
                    track.control = f"{base_url.rstrip('/')}{sep}{ctrl.lstrip('/')}"
            elif a.startswith("rtpmap:"):
                m = re.match(r"rtpmap:(\d+)\s+([A-Za-z0-9]+)(?:/(\d+))?", a)
                if m and int(m.group(1)) == pt:
                    track.encoding = m.group(2).upper()
                    if m.group(3):
                        track.clock_rate = int(m.group(3))
            elif a.startswith("fmtp:"):
                m = re.match(r"fmtp:(\d+)\s+(.*)", a)
                if m and int(m.group(1)) == pt:
                    for kv in m.group(2).split(";"):
                        if "=" in kv:
                            k, v = kv.split("=", 1)
                            track.fmtp[k.strip()] = v.strip()

        if track.encoding in ("H264",):
            sprop = track.fmtp.get("sprop-parameter-sets", "")
            for chunk in sprop.split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    nal = base64.b64decode(chunk)
                except Exception:
                    continue
                if nal:
                    nal_type = nal[0] & 0x1F
                    if nal_type == 7:
                        track.sps.append(nal)
                    elif nal_type == 8:
                        track.pps.append(nal)
        elif track.encoding in ("H265", "HEVC"):
            track.vps = _b64_params(track.fmtp, "sprop-vps")
            track.sps = _b64_params(track.fmtp, "sprop-sps")
            track.pps = _b64_params(track.fmtp, "sprop-pps")

        return track
    return None


# ---------- Authentication helpers ----------

def _digest_header(username: str, password: str, method: str, uri: str, challenge: dict) -> str:
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    qop = challenge.get("qop")
    opaque = challenge.get("opaque")
    algorithm = challenge.get("algorithm", "MD5").upper()
    if algorithm not in ("MD5", "MD5-SESS"):
        raise RtspError(f"Unsupported Digest algorithm: {algorithm}")

    def md5(s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    ha1 = md5(f"{username}:{realm}:{password}")
    if algorithm == "MD5-SESS":
        cnonce = md5(f"{os.urandom(8).hex()}")
        ha1 = md5(f"{ha1}:{nonce}:{cnonce}")
    else:
        cnonce = md5(f"{os.urandom(8).hex()}")
    ha2 = md5(f"{method}:{uri}")

    if qop:
        nc = "00000001"
        response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        parts = [
            f'username="{username}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'algorithm={algorithm}',
            f'response="{response}"',
            f'qop={qop}',
            f'nc={nc}',
            f'cnonce="{cnonce}"',
        ]
    else:
        response = md5(f"{ha1}:{nonce}:{ha2}")
        parts = [
            f'username="{username}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'response="{response}"',
        ]
    if opaque:
        parts.append(f'opaque="{opaque}"')
    return "Digest " + ", ".join(parts)


def _parse_challenge(header_value: str) -> tuple[str, dict]:
    """Return (scheme, params) for a WWW-Authenticate header."""
    scheme, _, rest = header_value.strip().partition(" ")
    params: dict[str, str] = {}
    for m in re.finditer(r'(\w+)=("([^"]*)"|([^,]+))', rest):
        key = m.group(1).lower()
        val = m.group(3) if m.group(3) is not None else m.group(4)
        params[key] = val.strip()
    return scheme.lower(), params


# ---------- Response parsing ----------

@dataclass
class RtspResponse:
    status: int
    reason: str
    headers: dict[str, str]
    body: bytes


def _recv_response(sock: socket.socket, buffered: bytearray) -> RtspResponse:
    """Read one RTSP response, keeping any trailing bytes in `buffered`."""
    # Read until we have the end of the header block.
    while b"\r\n\r\n" not in buffered:
        chunk = sock.recv(4096)
        if not chunk:
            raise RtspError("RTSP connection closed before response headers")
        buffered.extend(chunk)
    header_end = buffered.index(b"\r\n\r\n") + 4
    header_bytes = bytes(buffered[:header_end])
    del buffered[:header_end]

    header_text = header_bytes.decode("iso-8859-1")
    status_line, _, header_block = header_text.partition("\r\n")
    m = re.match(r"RTSP/\d\.\d\s+(\d+)\s+(.*)", status_line)
    if not m:
        raise RtspError(f"Malformed RTSP status line: {status_line!r}")
    status = int(m.group(1))
    reason = m.group(2).strip()

    headers: dict[str, str] = {}
    for line in header_block.split("\r\n"):
        if not line:
            continue
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()

    body_len = int(headers.get("content-length", "0") or "0")
    while len(buffered) < body_len:
        chunk = sock.recv(4096)
        if not chunk:
            raise RtspError("RTSP connection closed inside response body")
        buffered.extend(chunk)
    body = bytes(buffered[:body_len])
    del buffered[:body_len]
    return RtspResponse(status=status, reason=reason, headers=headers, body=body)


# ---------- The client itself ----------

class RtspClient:
    """Blocking RTSP-over-TCP client. One video track, TCP-interleaved transport."""

    def __init__(self, url: str, user_agent: str = "RTSPoofing-NVR/0.1", timeout: float = DEFAULT_TIMEOUT_S):
        parts = urlsplit(url)
        if parts.scheme.lower() != "rtsp":
            raise RtspError(f"Not an rtsp:// URL: {url!r}")
        self._timeout = timeout
        self._user_agent = user_agent

        self.username = parts.username or ""
        self.password = parts.password or ""
        self.host = parts.hostname or ""
        self.port = parts.port or DEFAULT_RTSP_PORT
        netloc = f"{self.host}:{self.port}"
        self.url = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))

        self._sock: Optional[socket.socket] = None
        self._cseq = 0
        self._session: Optional[str] = None
        self._session_timeout = 60
        self._auth_header: Optional[str] = None
        self._buffered = bytearray()
        self._keepalive_stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()

        self.track: Optional[VideoTrack] = None

    def connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=self._timeout)
        # Big recv buffer helps smooth out keyframe bursts on tight networks.
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        except OSError:
            pass

    def close(self) -> None:
        self._keepalive_stop.set()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=1.0)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def sock(self) -> socket.socket:
        if self._sock is None:
            raise RtspError("Not connected")
        return self._sock

    @property
    def leftover(self) -> bytes:
        """Bytes already received past the last RTSP response (interleaved frames may be here)."""
        return bytes(self._buffered)

    def consume_leftover(self) -> bytes:
        data = bytes(self._buffered)
        self._buffered.clear()
        return data

    # ----- request/response plumbing -----

    def _send_request(self, method: str, uri: str, extra_headers: Optional[dict[str, str]] = None, body: bytes = b"") -> RtspResponse:
        if self._sock is None:
            raise RtspError("Not connected")
        self._cseq += 1
        headers = {
            "CSeq": str(self._cseq),
            "User-Agent": self._user_agent,
        }
        if self._session:
            headers["Session"] = self._session
        if self._auth_header:
            headers["Authorization"] = self._auth_header
        if body:
            headers["Content-Length"] = str(len(body))
        if extra_headers:
            headers.update(extra_headers)

        lines = [f"{method} {uri} RTSP/1.0"]
        for k, v in headers.items():
            lines.append(f"{k}: {v}")
        request = "\r\n".join(lines).encode("iso-8859-1") + b"\r\n\r\n" + body
        with self._write_lock:
            self._sock.sendall(request)
        return _recv_response(self._sock, self._buffered)

    def _request(self, method: str, uri: str, extra_headers: Optional[dict[str, str]] = None, body: bytes = b"") -> RtspResponse:
        """Send a request, retry once with auth if 401."""
        resp = self._send_request(method, uri, extra_headers, body)
        if resp.status == 401 and self._auth_header is None and (self.username or self.password):
            scheme, params = _parse_challenge(resp.headers.get("www-authenticate", ""))
            if scheme == "digest":
                self._auth_header = _digest_header(self.username, self.password, method, uri, params)
            elif scheme == "basic":
                token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
                self._auth_header = f"Basic {token}"
            else:
                raise RtspError(f"Unsupported auth scheme: {scheme}")
            resp = self._send_request(method, uri, extra_headers, body)
        if resp.status >= 400:
            raise RtspError(f"{method} {uri} -> {resp.status} {resp.reason}")
        return resp

    # ----- high-level RTSP methods -----

    def options(self) -> RtspResponse:
        return self._request("OPTIONS", self.url)

    def describe(self) -> VideoTrack:
        resp = self._request("DESCRIBE", self.url, extra_headers={"Accept": "application/sdp"})
        content_base = resp.headers.get("content-base") or resp.headers.get("content-location") or self.url
        if not content_base.endswith("/") and "?" not in content_base:
            # Some cameras send a bare URL as Content-Base; the control URL is
            # typically appended as a path segment, so a trailing slash makes
            # relative control resolution behave.
            content_base = content_base + "/"
        track = parse_sdp_video(resp.body.decode("iso-8859-1", "replace"), content_base)
        if track is None:
            raise RtspError("No video track in SDP")
        self.track = track
        return track

    def setup(self, rtp_channel: int = 0) -> None:
        if self.track is None:
            raise RtspError("Call describe() before setup()")
        self.track.rtp_channel = rtp_channel
        self.track.rtcp_channel = rtp_channel + 1
        transport = f"RTP/AVP/TCP;unicast;interleaved={rtp_channel}-{rtp_channel + 1}"
        resp = self._request("SETUP", self.track.control, extra_headers={"Transport": transport})
        session_hdr = resp.headers.get("session", "")
        if not session_hdr:
            raise RtspError("No Session header in SETUP response")
        if ";" in session_hdr:
            sid, _, rest = session_hdr.partition(";")
            self._session = sid.strip()
            m = re.search(r"timeout\s*=\s*(\d+)", rest)
            if m:
                self._session_timeout = int(m.group(1))
        else:
            self._session = session_hdr.strip()

        # Honor server-chosen interleaved channels if different.
        got_transport = resp.headers.get("transport", "")
        m = re.search(r"interleaved=(\d+)-(\d+)", got_transport)
        if m:
            self.track.rtp_channel = int(m.group(1))
            self.track.rtcp_channel = int(m.group(2))

    def play(self, range_header: str = "npt=0.000-") -> None:
        self._request("PLAY", self.url, extra_headers={"Range": range_header})
        # After PLAY we hand the socket to the interleaved reader, which should
        # block indefinitely on recv() — the handshake timeout would otherwise
        # abort the stream during any quiet second.
        if self._sock is not None:
            self._sock.settimeout(None)
        self._start_keepalive()

    def teardown(self) -> None:
        self._keepalive_stop.set()
        if self._session is None:
            return
        try:
            self._send_request("TEARDOWN", self.url)
        except (OSError, RtspError):
            pass
        self._session = None

    # ----- keepalive -----

    def _start_keepalive(self) -> None:
        interval = max(10, self._session_timeout // 2)

        def loop() -> None:
            while not self._keepalive_stop.wait(interval):
                if self._sock is None or self._session is None:
                    return
                self._cseq += 1
                req = (
                    f"GET_PARAMETER {self.url} RTSP/1.0\r\n"
                    f"CSeq: {self._cseq}\r\n"
                    f"Session: {self._session}\r\n"
                    f"User-Agent: {self._user_agent}\r\n"
                )
                if self._auth_header:
                    req += f"Authorization: {self._auth_header}\r\n"
                req += "\r\n"
                try:
                    with self._write_lock:
                        self._sock.sendall(req.encode("iso-8859-1"))
                except OSError:
                    return
                # The RTSP response arrives interleaved with RTP data on the
                # same socket; the orchestrator's parser already surfaces
                # non-'$' bytes to a text callback, so we don't read it here.

        self._keepalive_thread = threading.Thread(target=loop, daemon=True, name="rtsp-keepalive")
        self._keepalive_thread.start()


# ---------- Interleaved framing on the TCP side ----------

def iter_interleaved(sock: socket.socket, seed: bytes = b""):
    """
    Yield (kind, channel_or_None, payload) tuples from an RTSP TCP connection
    after PLAY has started.

    - ('rtp', channel, payload) — one interleaved $-framed packet.
    - ('text', None, chunk)     — non-RTP bytes (RTSP responses to keepalives).

    Caller owns the socket's lifetime.
    """
    buf = bytearray(seed)
    while True:
        if len(buf) < 4:
            chunk = sock.recv(65536)
            if not chunk:
                return
            buf.extend(chunk)
            continue

        idx = buf.find(b"$")
        if idx == -1:
            # Flush everything as text and keep reading.
            text = bytes(buf)
            buf.clear()
            if text:
                yield ("text", None, text)
            continue
        if idx > 0:
            yield ("text", None, bytes(buf[:idx]))
            del buf[:idx]
            continue

        if len(buf) < 4:
            chunk = sock.recv(65536)
            if not chunk:
                return
            buf.extend(chunk)
            continue

        channel = buf[1]
        length = struct.unpack_from("!H", buf, 2)[0]
        # Sanity: too-tiny or absurdly huge → treat the '$' as noise.
        if length < 2 or length > (1 << 18):
            yield ("text", None, bytes(buf[:1]))
            del buf[:1]
            continue

        needed = 4 + length
        while len(buf) < needed:
            chunk = sock.recv(65536)
            if not chunk:
                return
            buf.extend(chunk)
        payload = bytes(buf[4:needed])
        del buf[:needed]
        yield ("rtp", channel, payload)
