//! proxy.rs — Async MITM proxy core.
//!
//! One MITMSession is spawned per accepted TCP connection.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
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

const CHUNK: usize = 65_536;

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ProxyConfig {
    pub mode:           Mode,
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
        let down_task = tokio::spawn(async move {
            let mut buf = vec![0u8; CHUNK];
            loop {
                tokio::select! {
                    result = cr.read(&mut buf) => {
                        match result {
                            Ok(0) | Err(_) => { stop_d.notify_waiters(); break; }
                            Ok(n) => {
                                debug!("NVR→CAM {} bytes", n);
                                if uw.write_all(&buf[..n]).await.is_err() {
                                    stop_d.notify_waiters(); break;
                                }
                                stats_d.down_bytes.fetch_add(n as u64, Ordering::Relaxed);
                            }
                        }
                    }
                    _ = stop_d.notified() => break,
                }
            }
        });

        // ── Upstream relay: camera → NVR ──────────────────────────────────
        let cfg_u         = self.cfg.clone();
        let inject_state_u = inject_state.clone();
        let inject_ready_u = inject_ready.clone();
        let stats_u        = stats.clone();
        let stop_u         = stop.clone();

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
                            if cw_up.lock().await.write_all(&text).await.is_err() {
                                stop_u2.notify_waiters();
                                return;
                            }
                        }
                        ParsedChunk::Frame(channel, payload) => {
                            if let Some(p) = probe.as_mut() {
                                if !inject_fired {
                                    let just_ready = p.feed(channel, &payload);
                                    if just_ready {
                                        if let Some(params) = p.params() {
                                            let mut st = inject_state_u.lock().await;
                                            st.inject_fps   = params.fps;
                                            st.inject_ssrc  = cfg_u.inject_ssrc.or(Some(params.ssrc));
                                            st.ts_per_frame = params.ts_per_frame();
                                            info!("Probe ready → FPS={:.2} SSRC={} PT={}",
                                                  params.fps, params.ssrc_hex(), params.pt);
                                        }
                                        inject_ready_u.notify_waiters();
                                        inject_fired = true;
                                    }
                                }
                            }

                            if let Some(hdr) = parse_rtp_header(&payload) {
                                let mut st = inject_state_u.lock().await;
                                st.last_live_seq = hdr.seq;
                                st.last_live_ts  = hdr.ts;
                            }

                            if let Some(tx) = &cap_u {
                                let limit = cfg_u.capture_frames;
                                let already = stats_u.captured.load(Ordering::Relaxed);
                                if limit == 0 || already < limit {
                                    if tx.try_send(CapMsg::Frame(channel, payload.clone())).is_err() {
                                        warn!("Capture channel full — dropped one frame from the .rtp file (live stream unaffected)");
                                    }
                                    let now = stats_u.captured.fetch_add(1, Ordering::Relaxed) + 1;
                                    if limit > 0 && now == limit {
                                        info!("Capture limit {} reached — stopping capture (still forwarding live stream).", limit);
                                        let _ = tx.try_send(CapMsg::Flush);
                                    }
                                }
                            }

                            if !cfg_u.inject_only {
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
                            let wire = build_interleaved(frame.channel, &new_payload);

                            {
                                let mut w = cw_i.lock().await;
                                if w.write_all(&wire).await.is_err() {
                                    stop_i.notify_waiters();
                                    break;
                                }
                            }

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

                            // Update seq/ts after send
                            inject_seq = inject_seq.wrapping_add(1);
                            inject_ts  = inject_ts.wrapping_add(ts_per_frame);
                        }
                        _ = rtcp_ticker.tick(), if rtcp_enabled => {
                            let (ntp_secs, ntp_frac) = ntp_now();
                            for (&channel, track) in rtcp_tracks.iter() {
                                let sr = build_sr(track.ssrc, ntp_secs, ntp_frac, track.last_rtp_ts,
                                                   track.pkt_count, track.octet_count);
                                let wire = build_interleaved(rtcp_channel_for(channel), &sr);
                                let mut w = cw_i.lock().await;
                                if w.write_all(&wire).await.is_err() {
                                    stop_i.notify_waiters();
                                    break;
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