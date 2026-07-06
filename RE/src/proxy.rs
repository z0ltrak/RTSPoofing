//! proxy.rs — Async MITM proxy core.
//!
//! One MITMSession is spawned per accepted TCP connection.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::io::{BufWriter, Write};
use std::fs::OpenOptions;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::{Mutex, Notify};
use tokio::time::{sleep, Instant};
use tracing::{debug, info, error};
use anyhow::Result;

use crate::capture::{write_frame, CapturedFrame};
use crate::parser::{InterleavedParser, ParsedChunk};
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
    up_bytes:   u64,
    down_bytes: u64,
    captured:   usize,
    injected:   usize,
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

        let (mut cr, mut cw) = tokio::io::split(client);
        let (mut ur, mut uw) = tokio::io::split(camera);

        let inject_state  = Arc::new(Mutex::new(InjectState {
            ts_per_frame: (90_000.0 / self.cfg.inject_fps.max(1.0)) as u32,
            inject_fps:   self.cfg.inject_fps,
            inject_ssrc:  self.cfg.inject_ssrc,
            ..Default::default()
        }));
        let inject_ready  = Arc::new(Notify::new());
        let stats         = Arc::new(Mutex::new(Stats::default()));
        let stop          = Arc::new(Notify::new());

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
                                stats_d.lock().await.down_bytes += n as u64;
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

        let cap_writer: Option<Arc<std::sync::Mutex<BufWriter<std::fs::File>>>> =
            if cfg_u.mode == Mode::Record {
                let f = OpenOptions::new()
                    .create(true).append(true)
                    .open(&cfg_u.capture_file)?;
                Some(Arc::new(std::sync::Mutex::new(BufWriter::with_capacity(256 * 1024, f))))
            } else {
                None
            };

        let cw_shared = Arc::new(Mutex::new(cw));
        let cw_inj    = cw_shared.clone();
        let cw_up     = cw_shared.clone();
        let cap_u     = cap_writer.clone();
        let stop_u2   = stop.clone();

        let up_task = tokio::spawn(async move {
            let mut buf    = vec![0u8; CHUNK];
            let mut parser = InterleavedParser::new();
            let mut probe  = if cfg_u.mode == Mode::Inject {
                Some(RTPProbe::new(cfg_u.inject_delay, 30))
            } else {
                None
            };

            let warmup_start     = Instant::now();
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
                stats_u.lock().await.up_bytes += n as u64;

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
                                    if !inject_fired && warmup_start.elapsed() >= cfg_u.inject_delay {
                                        inject_ready_u.notify_waiters();
                                        inject_fired = true;
                                        info!("Warm-up elapsed (time-based) — starting injection");
                                    }
                                }
                            }

                            if let Some(hdr) = parse_rtp_header(&payload) {
                                let mut st = inject_state_u.lock().await;
                                st.last_live_seq = hdr.seq;
                                st.last_live_ts  = hdr.ts;
                            }

                            if let Some(cap) = &cap_u {
                                {
                                    let mut w = cap.lock().unwrap();
                                    let _ = write_frame(&mut *w, channel, &payload);
                                }
                                let mut st = stats_u.lock().await;
                                st.captured += 1;
                                let limit = cfg_u.capture_frames;
                                if limit > 0 && st.captured >= limit {
                                    info!("Capture limit {} reached — stopping capture.", limit);
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

            if let Some(cap) = &cap_u {
                if let Ok(mut w) = cap.lock() {
                    let _ = w.flush();
                }
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

                loop {
                    tokio::select! {
                        _ = stop_i.notified() => break,
                        _ = async {
                            let t0 = Instant::now();

                            let frame = &frames[idx % frames.len()];
                            idx += 1;

                            let new_payload = rtp_rewrite(&frame.payload, inject_seq, inject_ts, inject_ssrc);
                            let wire = build_interleaved(frame.channel, &new_payload);

                            {
                                let mut w = cw_i.lock().await;
                                if w.write_all(&wire).await.is_err() {
                                    stop_i.notify_waiters();
                                    return;
                                }
                            }

                            {
                                let mut st = stats_i.lock().await;
                                st.injected += 1;
                                if st.injected % 100 == 0 {
                                    debug!("Injected {} frames (seq={})", st.injected, inject_seq);
                                }
                            }

                            // Update seq/ts after send
                            inject_seq = inject_seq.wrapping_add(1);
                            inject_ts  = inject_ts.wrapping_add(ts_per_frame);

                            // Pacing
                            tokio::task::yield_now().await;
                        } => {}
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

        let st = stats.lock().await;
        info!(
            "Tunnel closed. up={}B down={}B captured={} injected={}",
            st.up_bytes, st.down_bytes, st.captured, st.injected
        );

        Ok(())
    }
}