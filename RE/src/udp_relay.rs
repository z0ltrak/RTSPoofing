//! udp_relay.rs — UDP socket pairs and peer bookkeeping for one media track
//! negotiated over UDP transport (as opposed to TCP-interleaved).
//!
//! A track needs four sockets, not two, because RTP/RTCP source ports matter:
//! some NVR/camera implementations validate that received media actually comes
//! *from* the port pair that was declared during SETUP.
//!
//!  - `cam_facing_*`  — the ports we told the CAMERA (`client_port=`). It sends
//!    its RTP/RTCP here.
//!  - `nvr_facing_*`  — the ports we told the NVR (`server_port=`). It expects
//!    RTP/RTCP to arrive *from* these, and sends its own RTCP receiver reports
//!    *to* these — so these are also the sockets we must send relayed/injected
//!    media from, to match what was declared.

use std::net::SocketAddr;
use anyhow::{Context, Result};
use tokio::net::UdpSocket;
use tracing::debug;

/// Bind two UDP sockets on consecutive ports (even RTP, odd RTCP) where
/// possible — some camera/NVR firmware validates that a declared
/// client_port/server_port pair is consecutive. Falls back to two independent
/// ephemeral ports after a few failed attempts; most real-world stacks don't
/// actually enforce adjacency, so that still works against those.
pub async fn bind_udp_pair(bind_addr: &str) -> Result<(UdpSocket, UdpSocket)> {
    for attempt in 0..8 {
        let first = UdpSocket::bind(format!("{bind_addr}:0"))
            .await
            .context("binding first UDP socket of a pair")?;
        let first_port = first.local_addr()?.port();

        if let Ok(second) = UdpSocket::bind(format!("{bind_addr}:{}", first_port + 1)).await {
            return Ok((first, second));
        }
        debug!("UDP port pair attempt {attempt}: {first_port}/{} unavailable, retrying", first_port + 1);
    }

    let first = UdpSocket::bind(format!("{bind_addr}:0")).await?;
    let second = UdpSocket::bind(format!("{bind_addr}:0")).await?;
    Ok((first, second))
}

/// One negotiated UDP media track: its four sockets plus the real peer
/// addresses learned from the SETUP request/response.
pub struct UdpTrack {
    pub channel: u8,

    pub cam_facing_rtp:  UdpSocket,
    pub cam_facing_rtcp: UdpSocket,
    pub nvr_facing_rtp:  UdpSocket,
    pub nvr_facing_rtcp: UdpSocket,

    pub nvr_addr_rtp:     SocketAddr,
    pub nvr_addr_rtcp:    SocketAddr,
    pub camera_addr_rtcp: SocketAddr,
}

/// A track whose camera-facing sockets and the NVR's real ports are known
/// (learned from the SETUP request), but whose camera-facing peer address
/// isn't yet — that arrives in the SETUP *response*, at which point this
/// becomes a full `UdpTrack`.
pub struct PendingUdpTrack {
    pub channel: u8,
    pub cam_facing_rtp:  UdpSocket,
    pub cam_facing_rtcp: UdpSocket,
    pub nvr_facing_rtp:  UdpSocket,
    pub nvr_facing_rtcp: UdpSocket,
    pub nvr_addr_rtp:  SocketAddr,
    pub nvr_addr_rtcp: SocketAddr,
}

impl PendingUdpTrack {
    pub fn finalize(self, camera_addr_rtcp: SocketAddr) -> UdpTrack {
        UdpTrack {
            channel: self.channel,
            cam_facing_rtp: self.cam_facing_rtp,
            cam_facing_rtcp: self.cam_facing_rtcp,
            nvr_facing_rtp: self.nvr_facing_rtp,
            nvr_facing_rtcp: self.nvr_facing_rtcp,
            nvr_addr_rtp: self.nvr_addr_rtp,
            nvr_addr_rtcp: self.nvr_addr_rtcp,
            camera_addr_rtcp,
        }
    }
}
