---
theme: default
background: '#0a0a0a'
colorSchema: dark
class: text-center
highlighter: shiki
lineNumbers: false
transition: slide-left
mdc: true
fonts:
  sans: 'Inter'
  mono: 'JetBrains Mono'
title: RTSPoofing
info: |
  ## RTSPoofing — Trust Me, I'm a Camera
  A practical MITM + RTP replay attack against RTSP video-surveillance streams.
---

# RTSPoofing
## *Trust Me, I'm a Camera* 🎥

<div class="mt-8 text-gray-400 text-xl">
How to convince an NVR you're a legitimate camera<br/>when you very much are not
</div>

<div class="mt-10 text-gray-500">
Martín López Aranburu<br/>
Barcelona Cybersecurity Congress · November 2026
</div>

<div class="mt-10 text-sm text-gray-600">
⚠️ Educational and authorized-testing purposes only.
</div>

---
layout: default
transition: fade
---

# Agenda

<div class="mt-8 max-w-2xl mx-auto text-left">
<v-clicks>

- **The trust problem** — why RTSP/RTP was never built to resist this
- **The attack, in three phases** — ARP spoof → MITM proxy → frame injection
- **A field story** — how a hardened corporate firewall accidentally helped us
- **What the NVR actually sees** — and why it can't tell the difference
- **Detection & defense** — what actually stops this
- **Takeaways** for anyone who buys, installs, or audits CCTV

</v-clicks>
</div>

---
layout: center
transition: fade
---

# Who here has IP cameras on their network?


<v-click>
<div class="mt-8 text-2xl text-green-400 text-center">
And who can say exactly what those cameras are sending?
</div>
<div class="mt-6 flex justify-center">
  <img src="/gifs/cat-stare.gif" class="rounded-lg" style="height:160px"/>
</div>
</v-click>

---
layout: center
transition: zoom-out
---

# The problem with IP cameras

<div class="grid grid-cols-2 gap-12 mt-8 text-left">
<div class="card">

### What you assume happens
```
📷 Camera → 🖥️ NVR
```
<div class="mt-4 text-gray-400">
Clean. Simple. Trusted.
</div>

</div>
<div v-click class="card">

### What actually happens
```
📷 Camera → 🦹 You → 🖥️ NVR
```
<div class="mt-4 text-red-400">
Not clean. Not simple.<br/>
Definitely not trusted.
</div>

</div>
</div>

---
layout: center
transition: slide-left
---

# What is RTSP?

<div class="text-left max-w-2xl mx-auto mt-4">

**Real Time Streaming Protocol** — the HTTP of video surveillance

```
DESCRIBE rtsp://192.168.1.64/stream RTSP/1.0
↓
200 OK — here's the SDP with the stream parameters

SETUP rtsp://192.168.1.64/stream/track1 RTSP/1.0
↓
200 OK — interleaved TCP channel assigned

PLAY rtsp://192.168.1.64/stream RTSP/1.0
↓
💥 This is where it gets interesting
```

</div>

<v-click>
<div class="mt-4 text-center text-yellow-400 text-lg">
All of this in plaintext. No mandatory encryption. No stream authentication.<br/>
In the overwhelming majority of real-world installs.
</div>
</v-click>

---
layout: default
transition: fade
---

# Anatomy of an RTP packet

<div class="text-left max-w-2xl mx-auto mt-2 font-mono text-sm">

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       Sequence Number        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Synchronization Source (SSRC) identifier            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    💣 your video goes here 💣                 |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

</div>

<v-click>
<div class="mt-4 grid grid-cols-3 gap-4 text-center text-sm">
  <div class="card">
    <div class="text-blue-300 font-bold">Sequence Number</div>
    <div class="text-gray-400 mt-1">Frame ordering.<br/>Must stay continuous.</div>
  </div>
  <div class="card">
    <div class="text-green-300 font-bold">Timestamp</div>
    <div class="text-gray-400 mt-1">90 kHz media clock.<br/>Must keep advancing.</div>
  </div>
  <div class="card">
    <div class="text-red-300 font-bold">SSRC</div>
    <div class="text-gray-400 mt-1">Sender identity.<br/>Must be impersonated.</div>
  </div>
</div>
</v-click>

<div class="mt-4 text-center text-gray-500 text-sm">
Three fields. Zero authentication. That's the whole attack surface.
</div>

---
layout: center
transition: slide-up
---

# The attack, in three phases

<div class="mt-6">
<v-clicks>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="step-badge" style="background:#dc2626">1</div>
  <div><span class="text-red-400 font-bold">ARP Spoofing</span> — convince the network we're the camera</div>
</div>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="step-badge" style="background:#ca8a04">2</div>
  <div><span class="text-yellow-400 font-bold">MITM Proxy</span> — transparently relay the RTSP/RTP session</div>
</div>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="step-badge" style="background:#16a34a">3</div>
  <div><span class="text-green-400 font-bold">Frame Injection</span> — swap the real frames for ours</div>
</div>

</v-clicks>
</div>

<v-click>
<div class="mt-6 text-center text-gray-400 italic">
And the NVR keeps recording the whole time, none the wiser.
</div>
</v-click>

---
layout: center
transition: zoom-out
---

# Phase 1: ARP Spoofing

<div class="grid grid-cols-2 gap-8 mt-4 text-left">
<div class="card">

**The problem:**<br/>
The camera and the NVR talk to each other directly. We don't exist to them.

**The fix:**<br/>
Poison both ARP caches.

```bash
arpspoof -i eth0 -t <NVR> <CAM>
arpspoof -i eth0 -t <CAM> <NVR>
```

Now both sides believe we're the other one.

</div>
<div v-click class="card">

**The result:**
```
📷 Camera
    ↓ "This is the NVR (MAC: us)"
🦹 Attacker box
    ↓ "This is the Camera (MAC: us)"
🖥️ NVR
```

Traffic now flows through us.<br/>
Neither side notices.

</div>
</div>

<v-click>
<div class="mt-4 text-center text-sm text-gray-500">
⚠️ Doesn't work on networks with Dynamic ARP Inspection (DAI) —<br/>
which is exactly what the corporate firewall on our test network had. Or so we thought.
</div>
</v-click>

---
layout: center
transition: slide-left
---

# Field story: the firewall helped us by accident

<div class="text-center text-gray-500 text-sm mb-4 italic">
We went into the corporate network expecting a dead end. We found an unwitting accomplice instead.
</div>
<div class="grid grid-cols-2 gap-8 mt-2 text-left text-sm">
<div class="card">

**What we expected:**
<div class="text-gray-400 mt-1 mb-3">DAI active → forged ARP dropped → attack dead on arrival.</div>

**What actually happened:**
<div class="text-gray-400 mt-1">The switch didn't block anything. It saw the same IP show up on a different port and simply updated its MAC table — because that's what switches do.</div>
<div class="mt-3 bg-black rounded p-3 font-mono text-xs">
MAC 00:11:22:33:44:55 → port 5 (camera)<br/>
MAC 00:0c:29:31:23:67 → port 12 (us)<br/>
<span class="text-yellow-400">⚠ MAC flap detected — updating table</span><br/>
<span class="text-green-400">→ traffic redirected to port 12. Thanks. 👍</span>
</div>
</div>
<div v-click class="card">

**The side effect:**
<div class="text-green-400 font-bold mt-1">The existing camera↔NVR TCP session drops on its own.</div>
<div class="text-gray-400 mt-1 mb-3">The NVR reconnects → this time through the proxy → done.</div>
<div class="bg-black rounded p-3 text-center">
  <div class="text-yellow-400 font-bold mb-1">The switch's implicit reasoning:</div>
  <div class="text-gray-300 italic text-sm">"I see a network anomaly.<br/>I'll redirect traffic to the attacker<br/>to keep the network consistent."</div>
  <div class="text-gray-500 text-xs mt-2">— unintended, but very cooperative</div>
</div>
</div>
</div>

---
layout: center
transition: zoom-out
---

# MAC flapping: the switch as an unwitting accomplice

<div class="mt-4 text-center text-gray-400 text-sm mb-4">Step by step, on the corporate network</div>
<div class="max-w-2xl mx-auto">
<v-clicks>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#dc2626">1</div>
  <div class="text-sm text-gray-300">We start ARP spoofing: announce <span class="text-yellow-400 font-mono">CAM_IP → ATTACKER_MAC</span> to the NVR</div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#ea580c">2</div>
  <div class="text-sm text-gray-300">The switch sees the same IP on two different ports → detects <span class="text-yellow-400 font-bold">MAC flapping</span></div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#ca8a04">3</div>
  <div class="text-sm text-gray-300">It updates its MAC table: the camera's IP now maps to <span class="text-green-400 font-bold">our port</span></div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#2563eb">4</div>
  <div class="text-sm text-gray-300">TCP traffic between NVR and camera arrives at us → the <span class="text-red-400 font-bold">session drops</span></div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#16a34a">5</div>
  <div class="text-sm text-gray-300">The NVR detects the drop and <span class="text-green-400 font-bold">auto-reconnects</span> — this time through the proxy</div>
</div>
<div class="flex items-start gap-3">
  <div class="step-badge-sm" style="background:#9333ea">6</div>
  <div class="text-sm text-gray-300">The proxy accepts the connection. <span class="text-yellow-400 font-bold">The switch just did our job for us.</span> 🤝</div>
</div>
</v-clicks>
</div>

---
layout: default
transition: fade
---

# Phase 2: The MITM proxy

<div class="mt-8 text-center">
  The proxy does <strong>three things at once</strong>:
</div>

<div class="mt-10 grid grid-cols-3 gap-6">

<v-click>
<div class="card">
  <div class="text-5xl mb-4">①</div>
  <div class="font-bold text-xl mb-3 text-blue-400">Transparent RTSP negotiation</div>
  <ul class="text-sm space-y-2 text-left">
    <li>• Intercepts <code>DESCRIBE</code>, <code>SETUP</code>, <code>PLAY</code></li>
    <li>• Forwards them to the real camera</li>
    <li>• Relays the responses back unmodified</li>
    <li class="text-green-400 font-medium">→ The NVR never sees a middleman</li>
  </ul>
</div>
</v-click>

<v-click>
<div class="card">
  <div class="text-5xl mb-4">②</div>
  <div class="font-bold text-xl mb-3 text-blue-400">Live RTP probing</div>
  <ul class="text-sm space-y-2 text-left">
    <li>• Analyzes the first frames in real time</li>
    <li>• Detects PT, SSRC, codec (H.264/H.265), FPS</li>
    <li class="text-green-400 font-medium">→ Zero manual configuration</li>
  </ul>
</div>
</v-click>

<v-click>
<div class="card">
  <div class="text-5xl mb-4">③</div>
  <div class="font-bold text-xl mb-3 text-blue-400">Injection channel</div>
  <ul class="text-sm space-y-2 text-left">
    <li>• Stream flows normally at first...</li>
    <li>• ...then, on cue, frames get swapped</li>
    <li>• Sequence numbers and timestamps rewritten</li>
    <li class="text-green-400 font-medium">→ Continuity preserved throughout</li>
  </ul>
</div>
</v-click>

</div>

---
layout: center
transition: slide-up
---

# RTPProbe: real-time auto-detection

<div class="text-left max-w-2xl mx-auto mt-4 text-sm">

For the first few seconds, the proxy **only listens**:

```
[00:00.0] 🔍 Analyzing stream...
[00:01.2] PT=96 seen 847 times → dynamic H264
[00:02.1] SSRC=0xDEAD1234 dominant (99.8% of frames)
[00:02.8] Estimated FPS: 25.0 Hz (via RTP timestamp deltas)
[00:03.0] Codec: H264 (fragmented FU-A detected)
[00:03.0] ✅ Probe complete — starting injection
```

</div>

<v-click>
<div class="mt-4 card text-center">
<div class="text-green-400 font-bold text-lg">How do you get FPS without any metadata?</div>
<div class="text-gray-300 mt-2">
Standard RTP video clock = 90,000 Hz.<br/>
3,600 ticks between two frames → 90000 / 3600 = <span class="text-yellow-400 font-bold">25 fps</span>
</div>
</div>
</v-click>

---
layout: center
transition: slide-left
---

# Phase 3: Frame injection

<div class="text-left max-w-2xl mx-auto mt-4">

Once the probe has its parameters, the injector:

<v-clicks>

**① Reads pre-recorded frames** from a `.rtp` file
- Captured earlier from the same camera
- Or generated from any video with `ffmpeg`

**② Rewrites every RTP frame:**
```rust
// keeps continuity with the live stream that preceded it
seq = last_live_seq.wrapping_add(idx + 1);
ts  = last_live_ts.wrapping_add(idx * ts_per_frame);
ssrc = detected_ssrc; // same SSRC the real camera used
```

**③ Paces frames on a fixed clock**, not "as fast as possible"
- One tick per `1 / fps` seconds, self-correcting, never bursts to catch up
- Getting this wrong is how you flood the NVR and get noticed

**④ The NVR receives perfectly valid-looking frames**
- Same sequence progression → no gaps
- Same SSRC → same apparent sender
- Continuous timestamps → no glitches

</v-clicks>

</div>

---
layout: center
transition: zoom-out
---

# What the NVR sees

<div class="grid grid-cols-2 gap-8 mt-6 text-center">
<div class="card">
  <div class="text-4xl mb-3">🎬</div>
  <div class="text-green-400 font-bold text-lg">Real stream</div>
  <div class="text-gray-400 mt-2 text-sm">Camera pointed at an empty<br/>parking lot at 3 AM</div>
</div>
<div v-click class="card">
  <div class="text-4xl mb-3">🎭</div>
  <div class="text-red-400 font-bold text-lg">Injected stream</div>
  <div class="text-gray-400 mt-2 text-sm">A looped recording of the same<br/>empty parking lot from yesterday</div>
</div>
</div>

<v-click>
<div class="mt-6 text-2xl text-yellow-400 text-center">
To the NVR: indistinguishable.
</div>
<div class="text-gray-400 mt-1 text-center">
Same protocol. Same parameters. Same apparent source.
</div>
</v-click>

<v-click>
<div class="flex justify-center mt-6">
  <img src="/gifs/cat-happy.gif" class="rounded-lg" style="height:150px"/>
</div>
<div class="mt-3 text-center text-lg text-gray-300">
The NVR: <span class="text-green-400">"All normal here. Recording. Nothing to report."</span>
</div>
</v-click>

---
layout: center
transition: slide-up
---

# What if the session is already established?

<div class="text-xl mt-4 text-gray-300 text-center">
The NVR is already connected to the camera when the proxy starts.<br/>
It's listening on port 554, but nobody's dialing in.
</div>

<v-click>
<div class="mt-6 card text-left max-w-xl mx-auto">

**Fix: `tcpkill`**

```bash
# Tear down the existing TCP session
tcpkill -9 -i eth0 host 192.168.1.64 and port 554
```

The NVR sees the disconnect → reconnects on its own → this time it goes through the proxy.

</div>
</v-click>

---
layout: center
transition: slide-left
---

# Two clocks: what's on screen vs. what's in the metadata

<div class="mt-4 text-gray-300 text-lg text-center">
Cameras actually carry two independent notions of "when":
</div>

<div class="grid grid-cols-2 gap-6 mt-4 text-left text-sm">
<div class="card">
  <div class="text-blue-400 font-bold mb-2">On-screen OSD timestamp <span class="tag tag-shipped ml-1">spoofed</span></div>
  <div class="text-gray-400">Burned directly into the video pixels by the camera firmware — the one a human actually looks at.<br/>
  <span class="text-green-400">✅ Free win: it's whatever timestamp the injected clip was recorded with.</span></div>
</div>
<div class="card">
  <div class="text-blue-400 font-bold mb-2">RTCP Sender Report (NTP) <span class="tag tag-shipped ml-1">spoofed</span></div>
  <div class="text-gray-400">A separate wall-clock field some VMS/forensic export tools read independently of the picture.<br/>
  <span class="text-green-400">✅ We fabricate our own SR every few seconds, stamped with real "now."</span></div>
</div>
</div>

<v-click>
<div class="mt-4 card text-left text-sm max-w-xl mx-auto">

The interesting finding isn't the RTCP mechanics — it's that **spoofing the picture already beats spoofing the metadata** for the audience that matters most: a human reviewing footage. RTCP tampering only matters against tooling that reads the wall clock instead of the frame. We built it anyway, because a technical audience will ask; it's not the headline risk.

</div>
</v-click>

---
layout: center
transition: zoom-out
---

# Where this actually works

<div class="mt-4 grid grid-cols-3 gap-4 text-left text-sm">

<v-clicks>

<div class="card">
  <div class="text-3xl mb-2 text-center">🏠</div>
  <div class="text-green-400 font-bold text-center">Home networks</div>
  <div class="text-gray-300 mt-2 text-center">Consumer router, no DAI.</div>
  <div class="text-green-400 mt-2 font-bold text-center">ARP spoof reliably works</div>
</div>

<div class="card">
  <div class="text-3xl mb-2 text-center">🏪</div>
  <div class="text-yellow-400 font-bold text-center">Small business</div>
  <div class="text-gray-300 mt-2 text-center">Unmanaged switch, no network hardening.</div>
  <div class="text-yellow-400 mt-2 font-bold text-center">Usually works</div>
</div>

<div class="card">
  <div class="text-3xl mb-2 text-center">📹</div>
  <div class="text-orange-400 font-bold text-center">Dedicated CCTV / NVR</div>
  <div class="text-gray-300 mt-2 text-center">Flat network, common consumer-grade brands, installers with no security training.</div>
  <div class="text-orange-400 mt-2 font-bold text-center">Often works</div>
</div>

</v-clicks>

</div>

<v-click>
<div class="mt-4 bg-red-950 rounded-lg p-3 text-center text-sm">
  <span class="text-red-400 font-bold">Where ARP spoofing does NOT work:</span>
  <span class="text-gray-300 ml-2">segmented corporate networks with DAI enforced correctly — and switches that don't quietly help you out</span>
</div>
</v-click>

<div class="mt-2 text-center text-xs text-gray-600">
Informal lab observations across our own test environments, not a controlled study.
</div>

---
layout: center
transition: fade
---

# Full architecture

<div class="text-left max-w-2xl mx-auto mt-4 font-mono text-sm">

```
┌─────────────┐         ┌──────────────────────┐         ┌─────────┐
│   IP Cam    │────────▶│   Attacker box       │────────▶│   NVR   │
│             │◀────────│                      │◀────────│         │
└─────────────┘  TCP    │  ┌────────────────┐  │  TCP    └─────────┘
                 RTSP    │  │  RTSP Proxy    │  │  RTSP
                 RTP     │  │  RTPProbe      │  │  RTP
                         │  │  Frame Inject  │  │  (modified)
                         │  └────────────────┘  │
                         └──────────────────────┘
                                   ↑
                         ARP spoof active:
                         CAM believes NVR = us
                         NVR believes CAM = us
```

</div>

---
layout: center
transition: slide-left
---

# Demo

<div class="flex justify-center mt-4">
  <img src="/gifs/let-it.gif" class="rounded-lg" style="height:250px"/>
</div>


---
layout: center
transition: zoom-out
---

# How do you actually stop this?

<div class="mt-4 grid grid-cols-2 gap-5 text-left text-sm max-w-2xl mx-auto">

<v-clicks>

<div class="card">
  <div class="text-blue-400 font-bold mb-2">🔒 Dedicated VLAN for cameras</div>
  <div class="text-gray-400">Isolate surveillance traffic from everything else on the network.</div>
</div>

<div class="card">
  <div class="text-blue-400 font-bold mb-2">🛡️ Dynamic ARP Inspection, done right</div>
  <div class="text-gray-400">Managed switches with DAI active — and MAC-flap handling that doesn't quietly reroute traffic to the anomaly.</div>
</div>

<div class="card">
  <div class="text-blue-400 font-bold mb-2">🔐 RTSP over TLS</div>
  <div class="text-gray-400">RTSPS encrypts the channel — the proxy can no longer read or rewrite the stream.</div>
</div>

<div class="card">
  <div class="text-blue-400 font-bold mb-2">📊 ARP / network monitoring</div>
  <div class="text-gray-400">Flag anomalous ARP table changes. Tooling: arpwatch, NDR/XDR.</div>
</div>

</v-clicks>

</div>

---
layout: center
transition: slide-up
---

# Takeaways

<div class="mt-6 text-left max-w-xl mx-auto">

<v-clicks>

- IP cameras trust **anything that talks TCP to them on the right port**
- RTSP/RTP has **no built-in stream authentication**
- The attack works **without touching the camera or the NVR firmware**
- Detection from the NVR alone is **close to impossible** without network-level monitoring
- Most of the home and SMB installs we tested were vulnerable **today, out of the box**

</v-clicks>

</div>

<v-click>
<div class="mt-6 text-center text-yellow-400 text-lg italic">
"If your security system can be fooled<br/>
by a few hundred lines of code...<br/>
maybe it isn't as secure as the sticker on the box suggests."
</div>
</v-click>

---
layout: center
transition: fade
---

# One last thought

<v-click>
<div class="flex justify-center mt-4">
  <img src="/gifs/meory-wipe.gif" class="rounded-lg" style="height:180px"/>
</div>

<div class="mt-6 card max-w-2xl mx-auto text-center">
  <div class="text-gray-500 text-sm mb-3">— Midnight Blue, on Dahua camera firmware</div>
  <div class="text-white text-xl italic leading-relaxed">
    "Since it is all code written by Dahua,<br/>
    <span class="text-red-400 font-bold">there must be a parsing bug somewhere.</span>"
  </div>
</div>
</v-click>

<v-click>
<div class="mt-4 text-center text-gray-500 text-sm">
Spoiler: there were several.
</div>
</v-click>

---
layout: center
transition: zoom-out
class: text-center
---

# RTSPoofing
## *Trust Me, I'm a Camera* 🎥

<div class="mt-8 text-gray-400">
Code available after the talk, for research and authorized testing.<br/>
Please use it responsibly — and get written authorization first.
</div>

<div class="mt-8 text-sm text-gray-600">
⚠️ This talk is for educational purposes.<br/>
Testing networks you don't own or have explicit authorization for is illegal.<br/>
I'm not responsible for what you do with this.
</div>

<div class="mt-8 text-3xl">
<v-click>Questions?</v-click>
</div>
