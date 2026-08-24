//! proxy.rs — Async MITM proxy core.
//!
//! One MITMSession is spawned per accepted TCP connection. Handles both RTSP
//! transports: TCP-interleaved (`$`-framed media inside the RTSP TCP
//! connection) and UDP (media as independent datagrams on negotiated ports,
//! set up by rewriting SETUP request/response Transport headers — see
//! `rtsp.rs` and `udp_relay.rs`).

use std::collections::HashMap;
use std::net::{IpAddr, SocketAddr};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use std::io::{BufWriter, Write};
use std::fs::OpenOptions;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::{mpsc, Mutex, Notify};
use tokio::time::MissedTickBehavior;
use tracing::{debug, info, error, warn};
use anyhow::Result;

use crate::capture::{write_frame, CapturedFrame};
use crate::parser::{InterleavedParser, ParsedChunk};
use crate::rtcp::{build_sr, ntp_now, rtcp_channel_for};
use crate::rtp_probe::{RTPProbe, rtp_rewrite, build_interleaved, parse_rtp_header};
use crate::rtsp::RtspTextScanner;
use crate::udp_relay::{bind_udp_pair, PendingUdpTrack, UdpTrack};

const CHUNK: usize = 65_536;

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ProxyConfig {
    pub mode:           Mode,
    pub bind:           String,       // interface the proxy's own sockets (TCP listener, UDP relay ports) use
    pub camera_host:    String,
    pub camera_port:    u16,
    pub capture_file:   PathBuf,
    pub capture_frames: usize,        // 0 = unlimited
    pub inject_delay:   Duration,
    pub inject_fps:     f64,
    pub inject_ssrc:    Option<u32>,
    pub inject_only:    bool,
    pub rtcp_sr_interval: Duration,   // 0 disables RTCP SR generation
}

#[derive(Debug, Clone, PartialEq)]
pub enum Mode { Record, Inject }

// ─────────────────────────────────────────────────────────────────────────────
// Shared injection state
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct InjectState {
    pub last_live_seq: u16,
    pub last_live_ts:  u32,
    pub ts_per_frame:  u32,
    pub inject_ssrc:   Option<u32>,
    pub inject_fps:    f64,
}

// ─────────────────────────────────────────────────────────────────────────────
// Session stats
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Default)]
struct Stats {
    up_bytes:   AtomicU64,
    down_bytes: AtomicU64,
    captured:   AtomicUsize,
    injected:   AtomicUsize,
}

// ─────────────────────────────────────────────────────────────────────────────
// Capture writer — off the hot relay path
// ─────────────────────────────────────────────────────────────────────────────

/// Messages sent to the dedicated blocking capture-writer task.
enum CapMsg {
    Frame(u8, Vec<u8>),
    Flush,
}

/// Running totals for one injected media channel's synthetic RTCP Sender Reports.
#[derive(Default)]
struct RtcpTrack {
    ssrc:        u32,
    last_rtp_ts: u32,
    pkt_count:   u32,
    octet_count: u32,
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared per-session UDP transport state
// ─────────────────────────────────────────────────────────────────────────────

/// A SETUP request has been seen and rewritten, and sockets are bound, but we're
/// still waiting for the camera's SETUP response to learn its real media ports.
type PendingSetups = Arc<Mutex<HashMap<String, PendingUdpTrack>>>; // keyed by CSeq
/// Finalized tracks, ready to relay/inject through, keyed by our internal channel id.
type UdpTracks = Arc<Mutex<HashMap<u8, Arc<UdpTrack>>>>;

// ─────────────────────────────────────────────────────────────────────────────
// Shared frame handling — used by both the TCP-interleaved and UDP paths so
// they can't drift apart.
// ─────────────────────────────────────────────────────────────────────────────

/// Handles one media frame received from the camera, regardless of transport:
/// feeds the auto-detect probe (firing injection readiness once it completes),
/// updates the live seq/ts the injector continues from, and captures to disk
/// in Record mode. Returns whether the frame should also be forwarded live to
/// the NVR (false when `--inject-only` is suppressing the real stream).
#[allow(clippy::too_many_arguments)]
async fn process_camera_frame(
    cfg:          &ProxyConfig,
    probe:        &mut Option<RTPProbe>,
    inject_fired: &mut bool,
    inject_state: &Mutex<InjectState>,
    inject_ready: &Notify,
    cap_tx:       &Option<mpsc::Sender<CapMsg>>,
    stats:        &Stats,
    channel:      u8,
    payload:      &[u8],
) -> bool {
    if let Some(p) = probe.as_mut() {
        if !*inject_fired {
            let just_ready = p.feed(channel, payload);
            if just_ready {
                if let Some(params) = p.params() {
                    let mut st = inject_state.lock().await;
                    st.inject_fps   = params.fps;
                    st.inject_ssrc  = cfg.inject_ssrc.or(Some(params.ssrc));
                    st.ts_per_frame = params.ts_per_frame();
                    info!("Probe ready → FPS={:.2} SSRC={} PT={}",
                          params.fps, params.ssrc_hex(), params.pt);
                }
                inject_ready.notify_waiters();
                *inject_fired = true;
            }
        }
    }

    if let Some(hdr) = parse_rtp_header(payload) {
        let mut st = inject_state.lock().await;
        st.last_live_seq = hdr.seq;
        st.last_live_ts  = hdr.ts;
    }

    if let Some(tx) = cap_tx {
        let limit = cfg.capture_frames;
        let already = stats.captured.load(Ordering::Relaxed);
        if limit == 0 || already < limit {
            if tx.try_send(CapMsg::Frame(channel, payload.to_vec())).is_err() {
                warn!("Capture channel full — dropped one frame from the .rtp file (live stream unaffected)");
            }
            let now = stats.captured.fetch_add(1, Ordering::Relaxed) + 1;
            if limit > 0 && now == limit {
                info!("Capture limit {} reached — stopping capture (still forwarding live stream).", limit);
                let _ = tx.try_send(CapMsg::Flush);
            }
        }
    }

    !cfg.inject_only
}

/// Bind a fresh track's four sockets and stash it as pending, given the NVR's
/// real (pre-rewrite) client_port from its SETUP request.
async fn handle_setup_request(
    cfg: &ProxyConfig,
    next_channel: &AtomicU8,
    nvr_ip: IpAddr,
    nvr_client_port: (u16, u16),
) -> Result<(u8, (u16, u16), PendingUdpTrack)> {
    let (cam_rtp, cam_rtcp) = bind_udp_pair(&cfg.bind).await?;
    let (nvr_rtp, nvr_rtcp) = bind_udp_pair(&cfg.bind).await?;
    let cam_ports = (cam_rtp.local_addr()?.port(), cam_rtcp.local_addr()?.port());
    let channel = next_channel.fetch_add(2, Ordering::Relaxed);

    let pending = PendingUdpTrack {
        channel,
        cam_facing_rtp:  cam_rtp,
        cam_facing_rtcp: cam_rtcp,
        nvr_facing_rtp:  nvr_rtp,
        nvr_facing_rtcp: nvr_rtcp,
        nvr_addr_rtp:  SocketAddr::new(nvr_ip, nvr_client_port.0),
        nvr_addr_rtcp: SocketAddr::new(nvr_ip, nvr_client_port.1),
    };
    Ok((channel, cam_ports, pending))
}

/// Spawn the three relay tasks for a finalized UDP track: camera→NVR RTP (with
/// the same probe/capture/forward handling the TCP-interleaved path uses),
/// camera→NVR RTCP passthrough, and NVR→camera RTCP receiver reports.
#[allow(clippy::too_many_arguments)]
fn spawn_udp_track_relay(
    track:        Arc<UdpTrack>,
    cfg:          Arc<ProxyConfig>,
    inject_state: Arc<Mutex<InjectState>>,
    inject_ready: Arc<Notify>,
    cap_tx:       Option<mpsc::Sender<CapMsg>>,
    stats:        Arc<Stats>,
    stop:         Arc<Notify>,
) {
    // camera → NVR: RTP (probe / capture / forward, same as the TCP path)
    {
        let track = track.clone();
        let cfg = cfg.clone();
        let inject_state = inject_state.clone();
        let inject_ready = inject_ready.clone();
        let cap_tx = cap_tx.clone();
        let stats = stats.clone();
        let stop = stop.clone();
        tokio::spawn(async move {
            let mut buf = vec![0u8; CHUNK];
            let mut probe = if cfg.mode == Mode::Inject {
                Some(RTPProbe::new(cfg.inject_delay, 30))
            } else {
                None
            };
            let mut inject_fired = false;

            loop {
                let n = tokio::select! {
                    r = track.cam_facing_rtp.recv_from(&mut buf) => match r {
                        Ok((n, _src)) => n,
                        Err(_) => { stop.notify_waiters(); break; }
                    },
                    _ = stop.notified() => break,
                };
                stats.up_bytes.fetch_add(n as u64, Ordering::Relaxed);
                let payload = &buf[..n];

                let should_forward = process_camera_frame(
                    &cfg, &mut probe, &mut inject_fired,
                    &inject_state, &inject_ready, &cap_tx, &stats,
                    track.channel, payload,
                ).await;

                if should_forward {
                    let _ = track.nvr_facing_rtp.send_to(payload, track.nvr_addr_rtp).await;
                }
            }
        });
    }

    // camera → NVR: RTCP (SR passthrough — suppressed in --inject-only, where
    // the injection task's own synthetic SR takes its place)
    {
        let track = track.clone();
        let cfg = cfg.clone();
        let stop = stop.clone();
        tokio::spawn(async move {
            let mut buf = vec![0u8; 2048];
            loop {
                let n = tokio::select! {
                    r = track.cam_facing_rtcp.recv_from(&mut buf) => match r {
                        Ok((n, _src)) => n,
                        Err(_) => { stop.notify_waiters(); break; }
                    },
                    _ = stop.notified() => break,
                };
                if !cfg.inject_only {
                    let _ = track.nvr_facing_rtcp.send_to(&buf[..n], track.nvr_addr_rtcp).await;
                }
            }
        });
    }

    // NVR → camera: RTCP receiver reports, so a real camera's stream doesn't
    // stall waiting for reports that never arrive.
    {
        let track = track.clone();
        let stop = stop.clone();
        tokio::spawn(async move {
            let mut buf = vec![0u8; 2048];
            loop {
                let n = tokio::select! {
                    r = track.nvr_facing_rtcp.recv_from(&mut buf) => match r {
                        Ok((n, _src)) => n,
                        Err(_) => { stop.notify_waiters(); break; }
                    },
                    _ = stop.notified() => break,
                };
                let _ = track.cam_facing_rtcp.send_to(&buf[..n], track.camera_addr_rtcp).await;
            }
        });
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MITMSession
// ─────────────────────────────────────────────────────────────────────────────

pub struct MITMSession {
    cfg:           Arc<ProxyConfig>,
    inject_frames: Arc<Vec<CapturedFrame>>,
}

impl MITMSession {
    pub fn new(cfg: Arc<ProxyConfig>, inject_frames: Arc<Vec<CapturedFrame>>) -> Self {
        Self { cfg, inject_frames }
    }

    pub async fn run(self, client: TcpStream) -> Result<()> {
        let camera_addr = format!("{}:{}", self.cfg.camera_host, self.cfg.camera_port);
        let camera = match tokio::time::timeout(
            Duration::from_secs(10),
            TcpStream::connect(&camera_addr),
        ).await {
            Ok(Ok(s))  => s,
            Ok(Err(e)) => { error!("Cannot connect to camera {}: {}", camera_addr, e); return Ok(()); }
            Err(_)     => { error!("Timeout connecting to camera {}", camera_addr); return Ok(()); }
        };

        info!("MITM tunnel open: client↔proxy↔camera({})", camera_addr);

        let nvr_ip    = client.peer_addr()?.ip();
        let camera_ip = camera.peer_addr()?.ip();

        let (mut cr, cw) = tokio::io::split(client);
        let (mut ur, mut uw) = tokio::io::split(camera);

        let inject_state  = Arc::new(Mutex::new(InjectState {
            ts_per_frame: (90_000.0 / self.cfg.inject_fps.max(1.0)) as u32,
            inject_fps:   self.cfg.inject_fps,
            inject_ssrc:  self.cfg.inject_ssrc,
            ..Default::default()
        }));
        let inject_ready  = Arc::new(Notify::new());
        let stats         = Arc::new(Stats::default());
        let stop          = Arc::new(Notify::new());

        // UDP-transport bookkeeping. Stays empty/unused for TCP-interleaved
        // sessions — nothing here ever fires unless a SETUP request explicitly
        // negotiates UDP, so the existing TCP-interleaved path is unaffected.
        let pending_setups: PendingSetups = Arc::new(Mutex::new(HashMap::new()));
        let udp_tracks: UdpTracks = Arc::new(Mutex::new(HashMap::new()));
        let next_channel = Arc::new(AtomicU8::new(0));
        let is_udp_session = Arc::new(AtomicBool::new(false));

        // Time-based warm-up fallback: fires injection after `inject_delay` regardless of
        // whether the camera is producing data. Without a dedicated timer, this check only
        // ran opportunistically inside the upstream frame loop below — so a stalled or silent
        // camera during warm-up would delay injection indefinitely instead of the configured
        // number of seconds.
        if self.cfg.mode == Mode::Inject {
            let ready_t = inject_ready.clone();
            let delay = self.cfg.inject_delay;
            let stop_t = stop.clone();
            tokio::spawn(async move {
                tokio::select! {
                    _ = tokio::time::sleep(delay) => ready_t.notify_waiters(),
                    _ = stop_t.notified() => {}
                }
            });
        }

        // ── Downstream relay: NVR → camera ────────────────────────────────
        let stop_d  = stop.clone();
        let stats_d = stats.clone();
        let cfg_d   = self.cfg.clone();
        let pending_d = pending_setups.clone();
        let next_channel_d = next_channel.clone();
        let is_udp_d = is_udp_session.clone();
        let down_task = tokio::spawn(async move {
            let mut buf = vec![0u8; CHUNK];
            let mut scanner = RtspTextScanner::new();
            loop {
                let n = tokio::select! {
                    r = cr.read(&mut buf) => match r {
                        Ok(0) | Err(_) => { stop_d.notify_waiters(); break; }
                        Ok(n) => n,
                    },
                    _ = stop_d.notified() => break,
                };
                stats_d.down_bytes.fetch_add(n as u64, Ordering::Relaxed);

                for msg in scanner.feed(&buf[..n]) {
                    let text = String::from_utf8_lossy(&msg).into_owned();
                    let mut out = msg;

                    if let Some(setup) = crate::rtsp::parse_setup_request(&text) {
                        match handle_setup_request(&cfg_d, &next_channel_d, nvr_ip, setup.client_port).await {
                            Ok((channel, cam_ports, pending)) => {
                                pending_d.lock().await.insert(setup.cseq.clone(), pending);
                                is_udp_d.store(true, Ordering::Relaxed);
                                info!("SETUP (UDP) intercepted on channel {}: NVR asked for client_port={:?}, camera told client_port={:?}",
                                      channel, setup.client_port, cam_ports);
                                out = crate::rtsp::rewrite_port_pair(&text, "client_port=", cam_ports).into_bytes();
                            }
                            Err(e) => {
                                warn!("Could not set up UDP relay for a SETUP request: {e} — forwarding unmodified; this track won't be recordable/injectable.");
                            }
                        }
                    }

                    debug!("NVR→CAM {} bytes", out.len());
                    if uw.write_all(&out).await.is_err() {
                        stop_d.notify_waiters();
                        return;
                    }
                }
            }
        });

        // ── Upstream relay: camera → NVR ──────────────────────────────────
        let cfg_u          = self.cfg.clone();
        let inject_state_u = inject_state.clone();
        let inject_ready_u = inject_ready.clone();
        let stats_u         = stats.clone();
        let stop_u          = stop.clone();
        let pending_u       = pending_setups.clone();
        let udp_tracks_u    = udp_tracks.clone();

        // Capture writes happen on a dedicated blocking thread so a slow disk
        // never stalls the live CAM→NVR relay (which shares this task).
        let cap_tx: Option<mpsc::Sender<CapMsg>> = if cfg_u.mode == Mode::Record {
            let (tx, mut rx) = mpsc::channel::<CapMsg>(1024);
            let path = cfg_u.capture_file.clone();
            let f = OpenOptions::new()
                .create(true).append(true)
                .open(&path)?;
            tokio::task::spawn_blocking(move || {
                let mut w = BufWriter::with_capacity(256 * 1024, f);
                while let Some(msg) = rx.blocking_recv() {
                    match msg {
                        CapMsg::Frame(channel, payload) => {
                            let _ = write_frame(&mut w, channel, &payload);
                        }
                        CapMsg::Flush => { let _ = w.flush(); }
                    }
                }
                let _ = w.flush();
            });
            Some(tx)
        } else {
            None
        };

        let cw_shared = Arc::new(Mutex::new(cw));
        let cw_inj    = cw_shared.clone();
        let cw_up     = cw_shared.clone();
        let cap_u     = cap_tx.clone();
        let stop_u2   = stop.clone();

        let up_task = tokio::spawn(async move {
            let mut buf    = vec![0u8; CHUNK];
            let mut parser = InterleavedParser::new();
            let mut rtsp_scanner = RtspTextScanner::new();
            let mut probe  = if cfg_u.mode == Mode::Inject {
                Some(RTPProbe::new(cfg_u.inject_delay, 30))
            } else {
                None
            };

            let mut inject_fired = false;

            loop {
                let n = tokio::select! {
                    r = ur.read(&mut buf) => match r {
                        Ok(0) | Err(_) => { stop_u.notify_waiters(); break; }
                        Ok(n) => n,
                    },
                    _ = stop_u.notified() => break,
                };

                debug!("CAM→proxy {} bytes", n);
                stats_u.up_bytes.fetch_add(n as u64, Ordering::Relaxed);

                let chunks = parser.feed(&buf[..n]);

                for chunk in chunks {
                    match chunk {
                        ParsedChunk::Text(text) => {
                            for msg in rtsp_scanner.feed(&text) {
                                let msg_text = String::from_utf8_lossy(&msg).into_owned();
                                let mut out = msg;

                                if let Some(resp) = crate::rtsp::parse_setup_response(&msg_text) {
                                    let pending = pending_u.lock().await.remove(&resp.cseq);
                                    if let Some(pending) = pending {
                                        let channel = pending.channel;
                                        let nvr_ports = (pending.nvr_addr_rtp.port(), pending.nvr_addr_rtcp.port());
                                        // We must also redirect `server_port` to our own nvr-facing
                                        // ports — otherwise the NVR would send its RTCP receiver
                                        // reports straight to the real camera, bypassing the proxy.
                                        let our_server_port = match (pending.nvr_facing_rtp.local_addr(), pending.nvr_facing_rtcp.local_addr()) {
                                            (Ok(a), Ok(b)) => (a.port(), b.port()),
                                            _ => (0, 0),
                                        };
                                        let camera_rtcp_addr = SocketAddr::new(camera_ip, resp.server_port.1);
                                        let track = Arc::new(pending.finalize(camera_rtcp_addr));

                                        udp_tracks_u.lock().await.insert(channel, track.clone());
                                        info!("SETUP response (UDP) — camera server_port={:?}, NVR told server_port={:?} — UDP relay live on channel {}",
                                              resp.server_port, our_server_port, channel);

                                        spawn_udp_track_relay(
                                            track, cfg_u.clone(), inject_state_u.clone(), inject_ready_u.clone(),
                                            cap_u.clone(), stats_u.clone(), stop_u2.clone(),
                                        );

                                        let rewritten = crate::rtsp::rewrite_port_pair(&msg_text, "client_port=", nvr_ports);
                                        let rewritten = crate::rtsp::rewrite_port_pair(&rewritten, "server_port=", our_server_port);
                                        out = rewritten.into_bytes();
                                    }
                                }

                                if cw_up.lock().await.write_all(&out).await.is_err() {
                                    stop_u2.notify_waiters();
                                    return;
                                }
                            }
                        }
                        ParsedChunk::Frame(channel, payload) => {
                            let should_forward = process_camera_frame(
                                &cfg_u, &mut probe, &mut inject_fired,
                                &inject_state_u, &inject_ready_u, &cap_u, &stats_u,
                                channel, &payload,
                            ).await;

                            if should_forward {
                                let wire = build_interleaved(channel, &payload);
                                if cw_up.lock().await.write_all(&wire).await.is_err() {
                                    stop_u2.notify_waiters();
                                    return;
                                }
                            }
                        }
                    }
                }
            }

            if let Some(tx) = &cap_u {
                let _ = tx.send(CapMsg::Flush).await;
            }
        });

        // ── Injection task ──────────────────────────────────────────────────
        let inj_task = if self.cfg.mode == Mode::Inject && !self.inject_frames.is_empty() {
            let frames    = self.inject_frames.clone();
            let state     = inject_state.clone();
            let cw_i      = cw_inj.clone();
            let stats_i   = stats.clone();
            let stop_i    = stop.clone();
            let ready_i   = inject_ready.clone();
            let cfg_i     = self.cfg.clone();
            let udp_tracks_i = udp_tracks.clone();
            let is_udp_i     = is_udp_session.clone();

            Some(tokio::spawn(async move {
                info!("Injection task started — waiting for warm-up signal.");
                ready_i.notified().await;
                info!("Injection starting ({} frames in loop).", frames.len());

                let (mut inject_seq, mut inject_ts, ts_per_frame, inject_ssrc, fps) = {
                    let st = state.lock().await;
                    (
                        st.last_live_seq.wrapping_add(1),
                        st.last_live_ts.wrapping_add(st.ts_per_frame),
                        st.ts_per_frame,
                        st.inject_ssrc,
                        st.inject_fps,
                    )
                };

                let interval_ns = (1_000_000_000.0 / fps.max(1.0)) as u64;
                let mut idx: usize = 0;

                // Fixed-rate ticker: paces injected frames at the detected/configured
                // FPS instead of firing as fast as the loop can spin. MissedTickBehavior::Delay
                // means a slow write (or scheduler hiccup) delays the next tick rather than
                // bursting frames afterward, so we never flood the NVR to catch up.
                let mut ticker = tokio::time::interval(Duration::from_nanos(interval_ns.max(1)));
                ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);

                // Per-channel RTCP Sender Report bookkeeping. A real camera emits its own
                // SR periodically with a wall-clock (NTP) timestamp; in --inject-only mode
                // nothing from the real camera reaches the NVR at all, so if we want the
                // NVR's wall-clock metadata to also say "now" instead of leaving it stale
                // or absent, we have to fabricate SRs for our own injected stream.
                let rtcp_enabled = cfg_i.rtcp_sr_interval > Duration::ZERO;
                let mut rtcp_tracks: HashMap<u8, RtcpTrack> = HashMap::new();
                let mut rtcp_ticker = tokio::time::interval(
                    cfg_i.rtcp_sr_interval.max(Duration::from_millis(1))
                );
                rtcp_ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
                rtcp_ticker.tick().await; // consume the immediate first tick — nothing sent yet

                loop {
                    tokio::select! {
                        _ = stop_i.notified() => break,
                        _ = ticker.tick() => {
                            let frame = &frames[idx % frames.len()];
                            idx += 1;

                            let new_payload = rtp_rewrite(&frame.payload, inject_seq, inject_ts, inject_ssrc);

                            // UDP sessions: send raw RTP straight to the NVR's real client_port,
                            // from the socket we declared as server_port. If this session is UDP
                            // but the track isn't finalized yet (SETUP still in flight), skip this
                            // tick's frame rather than risk writing $-framed bytes into what the
                            // NVR still expects to be plain RTSP control text.
                            let mut sent = false;
                            if is_udp_i.load(Ordering::Relaxed) {
                                if let Some(track) = udp_tracks_i.lock().await.get(&frame.channel) {
                                    sent = track.nvr_facing_rtp.send_to(&new_payload, track.nvr_addr_rtp).await.is_ok();
                                }
                            } else {
                                let wire = build_interleaved(frame.channel, &new_payload);
                                let mut w = cw_i.lock().await;
                                if w.write_all(&wire).await.is_err() {
                                    stop_i.notify_waiters();
                                    break;
                                }
                                sent = true;
                            }

                            if sent {
                                let injected = stats_i.injected.fetch_add(1, Ordering::Relaxed) + 1;
                                if injected % 100 == 0 {
                                    debug!("Injected {} frames (seq={})", injected, inject_seq);
                                }

                                if rtcp_enabled {
                                    let used_ssrc = parse_rtp_header(&new_payload).map(|h| h.ssrc).unwrap_or(0);
                                    let payload_bytes = new_payload.len().saturating_sub(12) as u32;
                                    let track = rtcp_tracks.entry(frame.channel).or_default();
                                    track.ssrc = used_ssrc;
                                    track.last_rtp_ts = inject_ts;
                                    track.pkt_count = track.pkt_count.wrapping_add(1);
                                    track.octet_count = track.octet_count.wrapping_add(payload_bytes);
                                }
                            }

                            // Update seq/ts after send
                            inject_seq = inject_seq.wrapping_add(1);
                            inject_ts  = inject_ts.wrapping_add(ts_per_frame);
                        }
                        _ = rtcp_ticker.tick(), if rtcp_enabled => {
                            let (ntp_secs, ntp_frac) = ntp_now();
                            let udp_snapshot = if is_udp_i.load(Ordering::Relaxed) {
                                Some(udp_tracks_i.lock().await)
                            } else {
                                None
                            };
                            for (&channel, track) in rtcp_tracks.iter() {
                                let sr = build_sr(track.ssrc, ntp_secs, ntp_frac, track.last_rtp_ts,
                                                   track.pkt_count, track.octet_count);
                                match udp_snapshot.as_ref().and_then(|m| m.get(&channel)) {
                                    Some(udp_track) => {
                                        let _ = udp_track.nvr_facing_rtcp.send_to(&sr, udp_track.nvr_addr_rtcp).await;
                                    }
                                    None if !is_udp_i.load(Ordering::Relaxed) => {
                                        let wire = build_interleaved(rtcp_channel_for(channel), &sr);
                                        let mut w = cw_i.lock().await;
                                        if w.write_all(&wire).await.is_err() {
                                            stop_i.notify_waiters();
                                            break;
                                        }
                                    }
                                    None => {} // UDP session, track not finalized yet — skip this round
                                }
                            }
                            debug!("Sent RTCP SR for {} channel(s), NTP={}.{}", rtcp_tracks.len(), ntp_secs, ntp_frac);
                        }
                    }
                }
            }))
        } else {
            None
        };

        stop.notified().await;

        down_task.abort();
        up_task.abort();
        if let Some(t) = inj_task { t.abort(); }

        info!(
            "Tunnel closed. up={}B down={}B captured={} injected={}",
            stats.up_bytes.load(Ordering::Relaxed),
            stats.down_bytes.load(Ordering::Relaxed),
            stats.captured.load(Ordering::Relaxed),
            stats.injected.load(Ordering::Relaxed),
        );

        Ok(())
    }
}
