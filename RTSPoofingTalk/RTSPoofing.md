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

<!--
Welcome + housekeeping. ~25–30 min including the demo, leave room for Q&A at the end.

Say up front: everything here was done in a controlled lab, with authorization,
against hardware I own or was explicitly allowed to test. Say it once, mean it,
move on — don't over-apologize for the rest of the talk.

Hook for the room: this isn't a zero-day. It's a well-known attack class
(ARP MITM + RTP replay) built into a working tool, plus one genuinely
surprising finding from testing it on a real corporate network. Set that
expectation now so nobody's waiting for a "new CVE" reveal that isn't coming.
-->

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

<!--
Quick read-through, don't dwell. This is here so the audience can track where
we are — especially useful since the field story (MAC flapping) interrupts
the "clean" narrative partway through.

If short on time later, the slide to trim is "Where this actually works" —
it's supporting color, not load-bearing for the argument.
-->

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

<!--
Actually pause here for hands. This works best as real audience interaction,
not rhetorical — most hands go up on the first question, almost none on the
second. That gap IS the talk in one gesture; let it land before continuing.
-->

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

<!--
Framing slide — keep it short, it's a setup for the rest of the talk, not a
technical claim yet. The "why" comes over the next two slides (RTSP + RTP).
-->

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

<!--
Keep this brief for a technical audience — most will know RTSP already.
The one thing to land explicitly: SETUP is a negotiation, not a fixed spec,
and *we* get to sit in the middle of that negotiation. That's the thread
that pays off later on the UDP-transport slides.

"Interleaved TCP channel assigned" here is deliberately the TCP-interleaved
case — mention in passing that UDP transport also exists and we'll come
back to it, so it's not a surprise later.
-->

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

<!--
This is the technical crux of the whole talk in one slide — everything from
here on is "how do we control these three fields." Worth slowing down for.

If asked "isn't there a MAC/signature anywhere in RTP?" — no, not in base
RTP/RTCP. SRTP exists and would fix this, essentially nobody in consumer/SMB
CCTV uses it. That's basically the same point as the RTSP-over-TLS slide
later, just at the transport vs. media-integrity layer — fine to flag now if
someone asks, otherwise let the defense slide cover it.
-->

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

<!--
Roadmap slide for the technical middle third of the talk. Point at each
number as you say it — this is the map the audience should be holding in
their head through the ARP spoof, field story, MAC-flap, and proxy slides
that follow.
-->

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

<!--
Standard technique, most of the technical audience already knows ARP
spoofing — move at a good pace, this isn't the interesting part yet.

The DAI caveat at the bottom is the setup for the next two slides — deliver
it a little too confidently ("so obviously this fails on a hardened
network...") because the payoff is that it didn't.
-->

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

<!--
This is the highlight of the talk — the one finding that isn't in a textbook.
Slow down here. Tell it as a story: we expected the DAI to kill the attack,
we were ready to move on, and instead the switch itself became the
attack's transport mechanism.

Be precise about what's actually novel: it's not that DAI failed to block
ARP spoofing (it worked as designed for that). It's that basic MAC-learning
behavior — a completely separate, unrelated switch feature — created a side
channel that got us the same outcome anyway. That distinction is worth
making explicitly if a network engineer in the audience pushes back.
-->

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

<!--
This is the mechanism behind the previous slide's story — the technical
"how," for anyone who wants the precise sequence rather than the narrative
version. Fine to go through this one a bit faster since the story slide
already did the emotional work.

Good moment for a rhetorical pause on step 6 before moving on.
-->

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

<!--
Transition from "here's the network trick" to "here's the actual tool."
Mention briefly it's a Rust/Tokio proxy — async, one task pair per
connection — if anyone asks about implementation later, that's the answer.

Item ① is also where UDP-transport support (later slides) hooks in: the
same intercepted SETUP exchange is what lets us rewrite Transport headers
for UDP sessions, not just relay TCP-interleaved ones.
-->

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

<!--
Nice small "aha" moment — good to slow down for the FPS math specifically,
it's a satisfying trick and easy to follow live.

If asked how PT/SSRC "dominant" is chosen: majority vote over a short
window, not just the first packet seen — matters because the first few
packets after PLAY can be noisy.
-->

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

<!--
This is the core mechanic — take time here, it's the payload of the whole
talk. The pacing point (③) is worth emphasizing on its own: an unpaced
injector that just blasts frames as fast as the network allows is a
real, easy mistake, and it's exactly the kind of thing that gets an attack
noticed (dropped/corrupted frames, obvious bursty behavior) instead of
staying invisible. Good candidate for an aside if you want one: this
specific bug existed in an earlier version of the tool and was found by
writing a real test harness against the compiled binary, not by inspection —
worth mentioning if you want a "here's what hardening this looked like"
beat, otherwise skip it and keep moving.
-->

---
layout: center
transition: slide-up
---

# Not every camera uses TCP

<div class="mt-4 text-gray-300 text-lg text-center">
RTSP's SETUP negotiates <strong>one of two transports</strong> — everything so far assumed the first:
</div>

<div class="grid grid-cols-2 gap-6 mt-4 text-left text-sm">
<div class="card">
  <div class="text-blue-400 font-bold mb-2">TCP-interleaved</div>
  <div class="text-gray-400"><code>interleaved=0-1</code> — RTP/RTCP framed inside the RTSP TCP connection itself. What we've shown so far.</div>
</div>
<div class="card">
  <div class="text-blue-400 font-bold mb-2">UDP <span class="tag tag-shipped ml-1">also supported</span></div>
  <div class="text-gray-400"><code>client_port=X-Y</code> — RTP/RTCP as independent datagrams on their own negotiated ports. More common in practice.</div>
</div>
</div>

<v-click>
<div class="mt-4 card text-left text-sm max-w-xl mx-auto">
The catch: ARP spoofing already puts us on-path at layer 2 — so UDP between camera and NVR would just get <strong>transparently IP-forwarded by the kernel</strong>, without ever reaching our code. Useless for injection: we need to actually own the datagrams, not just route them.
</div>
</v-click>

<!--
This pair of slides is the newest part of the tool — say so, it's fine to
frame it as "since building this we've also added..." rather than pretending
it was always there.

The key point to land clearly: being on-path at L2 (ARP spoof) is NOT the
same as being on-path at the application layer. That distinction is easy to
gloss over and it's the entire reason the next slide's technique is
necessary instead of "just let the kernel forward it."
-->

---
layout: center
transition: zoom-out
---

# The fix: rewrite the negotiation, not just the network

<div class="mt-4 text-center text-gray-400 text-sm mb-4">Same MITM idea as ARP spoofing, one layer up — applied to the SETUP handshake we already control</div>
<div class="max-w-2xl mx-auto">
<v-clicks>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#dc2626">1</div>
  <div class="text-sm text-gray-300">NVR's SETUP says <span class="text-yellow-400 font-mono">client_port=8000-8001</span> — we swap it for ports <span class="text-green-400 font-bold">we</span> own before forwarding to the camera</div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#ea580c">2</div>
  <div class="text-sm text-gray-300">Camera now unknowingly sends its RTP/RTCP <span class="text-yellow-400 font-bold">straight to us</span></div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#ca8a04">3</div>
  <div class="text-sm text-gray-300">Camera's response says <span class="text-yellow-400 font-mono">server_port=9000-9001</span> — we swap that for ports we own too, and restore the NVR's own <code>client_port</code> so it isn't confused</div>
</div>
<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#2563eb">4</div>
  <div class="text-sm text-gray-300">NVR now unknowingly sends its RTCP receiver reports <span class="text-yellow-400 font-bold">straight to us</span> too</div>
</div>
<div class="flex items-start gap-3">
  <div class="step-badge-sm" style="background:#16a34a">5</div>
  <div class="text-sm text-gray-300">Four sockets later, <span class="text-green-400 font-bold">same capture/inject/RTCP-SR pipeline</span> as TCP-interleaved — neither side ever notices the ports moved</div>
</div>
</v-clicks>
</div>

<v-click>
<div class="mt-4 text-center text-sm text-gray-500">
Same auto-detection, same fixed-interval pacing, same forged RTCP timestamps — the transport underneath is invisible to everything downstream.
</div>
</v-click>

<!--
If asked "why four sockets and not two": source ports matter. Some
NVR/camera implementations validate that received RTP/RTCP actually comes
from the port pair that was declared during SETUP, so relaying/injecting
has to send from the socket each side was told about, not just any socket
that happens to reach them. Good technical-depth answer to have ready.

Last line (v-click) is the thesis of these two slides — worth reading
verbatim rather than paraphrasing, it's the cleanest summary in the deck.
-->

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

<!--
Breather slide after the dense UDP material — let the humor land, don't
rush the gif. This is also a natural point to check the room / take a quick
question if one's pending before moving into the more procedural slides.
-->

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

<!--
Practical/operational slide — this is genuinely useful for anyone trying to
replicate the setup, and a common real-world snag (NVRs are almost always
already connected by the time you're in position to intercept). Keep brief.
-->

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

<!--
This slide exists specifically to pre-empt the "but what about RTCP
timestamps" question from anyone who's read the RFC — answer it before
they ask it. If someone asks anyway, that's fine, point back to this slide.

The v-click text is the actual point of the slide; don't let the two cards
above it read as the takeaway on their own — they're setup.
-->

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

<!--
Deliberately qualitative, not percentages — say the "informal, not a
controlled study" line out loud if someone in Q&A pushes on numbers,
don't let it slide as just fine print. Optional to trim if running long;
nothing later depends on this slide specifically.
-->

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

<!--
Recap slide before the demo — good place to pause and take a question or
two if the room has one queued up, since the demo itself shouldn't be
interrupted once it starts.

Also the moment to double-check the demo environment is actually up
(cameras/NVR reachable, proxy binary built, terminal font size readable
from the back of the room) if that hasn't been confirmed already.
-->

---
layout: center
transition: slide-left
---

# Demo

<div class="flex justify-center mt-4">
  <img src="/gifs/let-it.gif" class="rounded-lg" style="height:250px"/>
</div>

<!--
LIVE DEMO — have a recorded backup ready and know how to get to it fast if
the venue network or hardware doesn't cooperate. Don't narrate apologies if
something's slow; just switch to the backup and keep talking.

Suggested beat: record mode first (show a normal stream + capture running),
then inject mode with --inject-only so the swap is unambiguous on screen,
then (if time) show the RTCP/OSD timestamp still reading "now" as the
callback to the "two clocks" slide.
-->

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

<!--
Land this constructively — after the demo, the room's attention is on "how
exposed am I," so this is the slide that actually earns its place. Don't
rush it just because it feels like a formality.

The DAI bullet is a deliberate callback to the field story: it's not enough
to turn DAI on, the MAC-flap handling has to not undo it.
-->

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

<!--
If time is short, this is the slide to expand to compensate — these five
lines are the entire argument of the talk distilled, safe to read close to
verbatim even if everything else got compressed.
-->

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

<!--
Deliver the quote straight, let the "spoiler" line get the laugh — don't
undercut the quote itself with commentary before the second click lands.
Good closing beat right before Q&A opens.
-->

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

<!--
Q&A. Likely questions to have crisp answers for:
- "Does this work over RTSPS/TLS?" — no, that's exactly what breaks it (see
  the defense slide) — the proxy needs to read/rewrite plaintext RTSP.
- "What about UDP source-port validation / NAT?" — covered on the UDP
  transport slides; four sockets per track specifically to satisfy that.
- "Have vendors been notified?" — answer honestly based on your actual
  disclosure status; don't overstate coordination that didn't happen.
- Where to get the code / how to reach you — have the repo URL and contact
  info ready to say out loud, not just on a slide people can't photograph
  in time.
-->
