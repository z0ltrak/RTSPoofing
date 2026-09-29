---
theme: default
background: '#05090b'
colorSchema: dark
class: text-center cover
highlighter: shiki
lineNumbers: false
transition: slide-left
mdc: true
fonts:
  sans: 'JetBrains Mono'
  mono: 'JetBrains Mono'
title: RTSPoofing
info: |
  ## RTSPoofing — Trust Me, I'm a Camera
  A practical MITM + RTP replay attack against RTSP video-surveillance streams.
---

# RTSPoofing
## *Trust Me, I'm a Camera* <mdi-cctv class="inline-block ml-1" />

<div class="mt-8 dim text-xl">
How to convince an NVR you're a legitimate camera
</div>

<div class="mt-10 dim">
Martín López Aranburu<br/>
Barcelona Cybersecurity Congress · November 2026
</div>

<div class="mt-10 text-sm dim flex items-center justify-center gap-1">
<mdi-alert class="warn inline-block" /> Educational and authorized-testing purposes only.
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
layout: center
transition: fade
---

# Who am I

<div class="mt-4 flex items-center justify-center gap-8">
  <img src="/img/martin-lopez.png" class="rounded-lg object-cover" style="width:140px;height:140px;border:2px solid var(--rt-border)" />
  <div class="text-left">
    <div class="text-2xl font-bold text-white">Martín López Aranburu</div>
    <div class="mt-1 dim">Cybersecurity Engineer</div>
  </div>
</div>

<div class="mt-6 max-w-md mx-auto">
<v-clicks>

<div class="card">
  <div class="accent font-bold text-sm flex items-center gap-2"><mdi-briefcase-outline class="inline-block" /> About me</div>
  <div class="dim text-sm mt-1">Cybersecurity Engineer at <strong>RDT</strong>. Author of <strong>RTSPoofing</strong>. Passionate about RE, Malware, and Exploiting.</div>
</div>

</v-clicks>
</div>

<div class="mt-4 card max-w-md mx-auto text-center">
  <div class="accent font-bold flex items-center justify-center gap-2"><mdi-linkedin class="inline-block" /> LinkedIn</div>
  <div class="mt-1 dim text-sm">linkedin.com/in/martín-lópez-aranburu</div>
</div>

<!--
whoami slide — keep it to 20-30 seconds. Name, photo, role at RDT, what
the tool is and why you built it, point at the LinkedIn if people want
to connect after. Don't turn this into a résumé recitation — the room
came for the attack, not the bio.
-->

---
layout: center
class: text-center
transition: fade
---

# Before we start

<div class="card inline-block text-left mt-6">

<div class="flex items-center gap-2"><mdi-check-bold class="good inline-block" /> Isolated lab environments, or explicit written authorization</div>
<div class="flex items-center gap-2 mt-1"><mdi-check-bold class="good inline-block" /> Not a zero-day — a known attack class, plus one genuinely new field finding</div>
<div class="flex items-center gap-2 mt-1"><mdi-check-bold class="good inline-block" /> Live demo, backup recording on standby if the venue network fights back</div>

</div>

<!--
Housekeeping, made visible instead of buried in notes. Say it once, mean
it, move on — don't over-apologize for the rest of the talk. Everything
here was done in a controlled lab, with authorization, against hardware I
own or was explicitly allowed to test.

Hook for the room: this isn't a zero-day. It's a well-known attack class
(ARP MITM + RTP replay) built into a working tool, plus one genuinely
surprising finding from testing it on a real corporate network. Set that
expectation now so nobody's waiting for a "new CVE" reveal that isn't coming.
-->

---
layout: section
transition: fade
---

# Part 1
## The trust problem

<!--
Act divider. Point at it, say the part title out loud, move on in under
5 seconds — this is a wayfinding beat for the room, not new content.
-->

---
layout: center
transition: fade
---

# Who here has IP cameras on their network?


<v-click>
<div class="mt-8 text-2xl good text-center">
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
Camera → NVR
```
<div class="mt-4 dim">
Clean. Simple. Trusted.
</div>

</div>
<div v-click class="card">

### What actually happens
```
Camera → You → NVR
```
<div class="mt-4 danger">
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
This is where it gets interesting
```

</div>

<v-click>
<div class="mt-4 text-center warn text-lg">
All of this in plaintext. No mandatory encryption. No stream authentication.<br/>
In the overwhelming majority of real-world installs.
</div>
</v-click>

<!--
Keep this brief for a technical audience — most will know RTSP already.
The one thing to land explicitly: SETUP is a negotiation, not a fixed spec,
and *we* get to sit in the middle of that negotiation.

"Interleaved TCP channel assigned" here is deliberately the TCP-interleaved
case, the only transport this cut of the talk covers. If asked: RTSPoofing
also supports UDP transport (rewriting the SETUP negotiation the same way,
one layer up), just out of scope for today's time slot.

This diagram skips over RTSP auth (Basic/Digest on these same requests) for
clarity — that's deliberate, not an oversight; it's addressed later on the
MITM proxy slide once "we're a transparent relay" has been established,
which is the fact that actually answers it.
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
|                     your video goes here                      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

</div>

<v-click>
<div class="mt-4 grid grid-cols-3 gap-4 text-center text-sm">
  <div class="card">
    <div class="accent font-bold">Sequence Number</div>
    <div class="dim mt-1">Frame ordering.<br/>Gaps OK, big jumps aren't.</div>
  </div>
  <div class="card">
    <div class="good font-bold">Timestamp</div>
    <div class="dim mt-1">90 kHz media clock.<br/>Should advance smoothly.</div>
  </div>
  <div class="card">
    <div class="danger font-bold">SSRC</div>
    <div class="dim mt-1">Sender identity.<br/>A change resets decode.</div>
  </div>
</div>
</v-click>

<div class="mt-4 text-center dim text-sm">
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

Be precise about "gaps are tolerated": RTP runs over UDP specifically because
loss is expected, so decoders conceal small sequence gaps rather than failing
outright — don't oversell fragility here, since a loss-tolerant receiver is
actually good news for the attack (more slack than a room might assume, not
less). What actually gets you noticed is a big/backward jump in sequence or
timestamp, or an SSRC that changes mid-stream and forces a decoder reset —
that's why the injector goes to the trouble of keeping all three continuous
rather than because any single dropped packet would blow the whole thing up.
-->

---
layout: section
transition: fade
---

# Part 2
## The attack

<!--
Act divider. Three phases, one field story, one MITM proxy under the hood
— everything through "What the NVR sees" lives in this act.
-->

---
layout: center
transition: slide-up
---

# The attack, in three phases

<div class="mt-6">
<v-clicks>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="step-badge" style="background:#ff3b52">1</div>
  <div><span class="danger font-bold">ARP Spoofing</span> — convince the network we're the camera</div>
</div>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="step-badge" style="background:#ffb347">2</div>
  <div><span class="warn font-bold">MITM Proxy</span> — transparently relay the RTSP/RTP session</div>
</div>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="step-badge" style="background:#39d98a">3</div>
  <div><span class="good font-bold">Frame Injection</span> — swap the real frames for ours</div>
</div>

</v-clicks>
</div>

<v-click>
<div class="mt-6 text-center dim italic">
And the NVR keeps recording the whole time, none the wiser.
</div>
</v-click>

<!--
Roadmap slide for the technical middle third of the talk. Point at each
number as you say it — this is the map the audience should be holding in
their head through the ARP spoof, field story, and proxy slides that
follow.
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
Camera
    ↓ "This is the NVR (MAC: us)"
Attacker box
    ↓ "This is the Camera (MAC: us)"
NVR
```

Traffic now flows through us.<br/>
Neither side notices.

</div>
</div>

<v-click>
<div class="mt-4 text-center text-sm dim">
<span class="inline-flex items-center gap-1"><mdi-alert class="warn inline-block" /> Doesn't work on networks with Dynamic ARP Inspection (DAI) —</span><br/>
which is exactly what the corporate firewall on our test network had. Or so we thought.
</div>
</v-click>

<!--
Standard technique, most of the technical audience already knows ARP
spoofing — move at a good pace, this isn't the interesting part yet.

The DAI caveat at the bottom is the setup for the field-story slide —
deliver it a little too confidently ("so obviously this fails on a
hardened network...") because the payoff is that it didn't, and the
honest reason why turns out to be more interesting than the first
explanation we had for it.
-->

---
layout: center
transition: slide-left
---

# Field story: we were wrong about why this worked

<div class="text-center dim text-sm mb-4 italic">
The best result of writing this up properly: going back with a real packet capture and catching our own mistake.
</div>
<div class="grid grid-cols-2 gap-8 mt-2 text-left text-sm">
<div class="card">

**What we first thought:**
<div class="dim mt-1 mb-3">DAI active → forged ARP dropped → attack dead on arrival. It wasn't. We assumed the switch's MAC-learning had relearned the camera onto our port and redirected traffic "by accident."</div>

**What the capture actually shows:**
<div class="dim mt-1">The camera's real MAC never appears on our port — not once, across 6,000+ frames. Everything with the camera's IP leaves with <em>our</em> MAC, because that's just what a relaying proxy does. No flap required, none possible.</div>

</div>
<div v-click class="card">

**So what dropped the session?**
<div class="danger font-bold mt-1">We did. The proxy itself sends the FIN.</div>
<div class="dim mt-1 mb-3">Three teardown → reconnect cycles, all traced to our own TCP handling — not the switch, not DAI, not a network event at all.</div>
<div class="console p-3 text-center">
  <div class="warn font-bold mb-1">Open question:</div>
  <div class="dim text-sm">Why DAI didn't block the spoofing in the first place is still unconfirmed.</div>
</div>
</div>
</div>

<!--
This used to be "the switch helped us by accident" — a MAC-flapping story.
It was wrong, and this slide corrects it live instead of quietly swapping
the deck. That correction is worth doing in front of the room: security
audiences respect "we checked our own claim and it didn't hold up" far
more than a tidy story that turns out to be unverified.

The actual sequence, if asked for detail: packet capture showed the
camera's real MAC never traverses the attacker's switch port — everything
with the camera's IP egresses with the proxy's own MAC, because the proxy
is a full TCP-terminating relay (two independent TCP stacks), never an L2-
transparent forward. MAC-table flapping requires the same MAC seen on two
ports; that can't happen here by construction. The repeated session drops
we'd attributed to the switch "redirecting to the anomaly" were actually
three FIN packets sent by the proxy itself, at irregular intervals — the
signature of an internal fault, not a periodic network event. The likely
culprit is somewhere in the pacing/segmentation path, but that hasn't been
isolated against this codebase yet — don't overclaim it live; "a bug in
our own connection handling, still being tracked down" is the honest
answer.

What's still genuinely unresolved: why the ARP spoofing wasn't blocked on
a network believed to have DAI enabled. That's an open question now, not
a solved one — say so plainly if asked. It may simply not have been
enforced the way it was assumed to be.
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
  <div class="font-bold text-xl mb-3 accent">Transparent relay</div>
  <ul class="text-sm space-y-2 text-left">
    <li>• Intercepts <code>DESCRIBE</code>, <code>SETUP</code>, <code>PLAY</code></li>
    <li>• Forwards them to the real camera</li>
    <li>• Relays the responses back unmodified</li>
    <li class="good font-medium">→ Never sees us, never needs the password</li>
  </ul>
</div>
</v-click>

<v-click>
<div class="card">
  <div class="text-5xl mb-4">②</div>
  <div class="font-bold text-xl mb-3 accent">Live RTP probing</div>
  <ul class="text-sm space-y-2 text-left">
    <li>• Analyzes the first frames in real time</li>
    <li>• Detects PT, SSRC, codec (H.264/H.265), FPS</li>
    <li class="dim text-xs">(FPS trick: 90kHz clock ÷ timestamp delta — no metadata needed)</li>
    <li class="good font-medium">→ Zero manual configuration</li>
  </ul>
</div>
</v-click>

<v-click>
<div class="card">
  <div class="text-5xl mb-4">③</div>
  <div class="font-bold text-xl mb-3 accent">Injection channel</div>
  <ul class="text-sm space-y-2 text-left">
    <li>• Stream flows normally at first...</li>
    <li>• ...then, on cue, frames get swapped</li>
    <li>• Sequence numbers and timestamps rewritten</li>
    <li class="good font-medium">→ Continuity preserved throughout</li>
  </ul>
</div>
</v-click>

</div>

<!--
Transition from "here's the network trick" to "here's the actual tool."
Mention briefly it's a Rust/Tokio proxy — async, one task pair per
connection — if anyone asks about implementation later, that's the answer.

The Authorization-header line preempts a question a security audience will
ask: "does this still work if the camera has a password on it?" Yes, and the
reason is worth stating precisely — this is a transparent byte relay, not a
new client authenticating on its own. The NVR already knows the camera's
credentials and computes its own Basic/Digest Authorization header same as
always; we just forward it untouched in both directions. We're not
bypassing auth, we're sitting inside a session two already-authenticated
parties are having. RTSP credentials protect against an unauthorized viewer
opening a new connection — they do nothing against an on-path relay of an
existing one.
-->

---
layout: center
transition: slide-left
---

# Phase 3: Frame injection

<div class="mt-4 text-center dim text-sm mb-3">Once the probe has its parameters, the injector:</div>
<div class="max-w-2xl mx-auto">
<v-clicks>

<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#4be8ff">1</div>
  <div class="text-sm dim"><strong class="text-white">Reads pre-recorded frames</strong> from a <code>.rtp</code> file — captured earlier from the same camera, or generated from any video with <code>ffmpeg</code></div>
</div>

<div class="mb-3">
  <div class="flex items-start gap-3 mb-1">
    <div class="step-badge-sm" style="background:#ff3b52">2</div>
    <div class="text-sm dim"><strong class="text-white">Rewrites every RTP frame</strong> — keeps continuity with the live stream that preceded it:</div>
  </div>
  <div class="console p-2 font-mono text-xs ml-10">
    seq = last_live_seq.wrapping_add(idx + 1);<br/>
    ts &nbsp;= last_live_ts.wrapping_add(idx * ts_per_frame);<br/>
    ssrc = detected_ssrc; <span class="dim">// same SSRC the real camera used</span>
  </div>
</div>

<div class="flex items-start gap-3 mb-3">
  <div class="step-badge-sm" style="background:#ffb347">3</div>
  <div class="text-sm dim"><strong class="text-white">Paces frames on a fixed clock</strong>, not "as fast as possible" — one tick per <code>1/fps</code>, self-correcting; bursting to catch up is what gets you noticed</div>
</div>

<div class="flex items-start gap-3">
  <div class="step-badge-sm" style="background:#39d98a">4</div>
  <div class="text-sm dim"><strong class="text-white">The NVR receives valid-looking frames</strong> — same sequence progression, same SSRC, continuous timestamps: no gaps, no glitches</div>
</div>

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
transition: zoom-out
---

# What the NVR sees

<div class="grid grid-cols-2 gap-8 mt-6 text-center">
<div class="card">
  <div class="text-4xl mb-3 good"><mdi-movie-open-outline class="inline-block" /></div>
  <div class="good font-bold text-lg">Real stream</div>
  <div class="dim mt-2 text-sm">Camera pointed at an empty<br/>parking lot at 3 AM</div>
</div>
<div v-click class="card">
  <div class="text-4xl mb-3 danger"><mdi-drama-masks class="inline-block" /></div>
  <div class="danger font-bold text-lg">Injected stream</div>
  <div class="dim mt-2 text-sm">A looped recording of the same<br/>empty parking lot from yesterday</div>
</div>
</div>

<v-click>
<div class="mt-6 text-2xl warn text-center">
To the NVR: indistinguishable.
</div>
<div class="dim mt-1 text-center">
Same protocol. Same parameters. Same apparent source.
</div>
</v-click>

<v-click>
<div class="flex justify-center mt-6">
  <img src="/gifs/cat-happy.gif" class="rounded-lg" style="height:150px"/>
</div>
<div class="mt-3 text-center text-lg dim">
The NVR: <span class="good">"All normal here. Recording. Nothing to report."</span>
</div>
</v-click>

<!--
Breather slide after Phase 3 — let the humor land, don't rush the gif.
This is also a natural point to check the room / take a quick question
if one's pending before moving into the demo.
-->

---
layout: section
transition: fade
---

# Part 3
## Demo, defense &amp; takeaways

<!--
Act divider into the home stretch: live demo, then the constructive
"how do you stop this" slide, then the five-line close.
-->

---
layout: center
transition: slide-up
---

# Demo

<div class="mt-4 mx-auto flex flex-col items-center justify-center gap-2" style="width:640px;height:360px;border:2px dashed rgba(255,255,255,0.2);border-radius:0.75rem;">
  <div class="text-5xl dim"><mdi-cctv class="inline-block" /></div>
  <div class="text-sm dim">Video placeholder — drop in the demo recording</div>
</div>

<!--
LIVE DEMO (or the recorded backup dropped into the placeholder above) —
have a recorded backup ready and know how to get to it fast if the venue
network or hardware doesn't cooperate. Don't narrate apologies if
something's slow; just switch to the backup and keep talking.

Suggested beat: record mode first (show a normal stream + capture running),
then inject mode with --inject-only so the swap is unambiguous on screen.
If asked, the injected stream's on-screen timestamp and RTCP metadata both
read "now," not whenever the clip was actually recorded — good one-liner
to have ready, cut from the slides for time.
-->

---
layout: center
transition: zoom-out
---

# How do you actually stop this?

<div class="mt-4 grid grid-cols-2 gap-5 text-left text-sm max-w-2xl mx-auto">

<v-clicks>

<div class="card">
  <div class="accent font-bold mb-2 flex items-center gap-2"><mdi-lock class="inline-block" /> Dedicated VLAN for cameras</div>
  <div class="dim">Isolate surveillance traffic from everything else on the network.</div>
</div>

<div class="card">
  <div class="accent font-bold mb-2 flex items-center gap-2"><mdi-shield-lock-outline class="inline-block" /> Dynamic ARP Inspection, verified</div>
  <div class="dim">Managed switches with DAI active — and actually tested against real spoofed ARP traffic, not just assumed to be enforced.</div>
</div>

<div class="card">
  <div class="accent font-bold mb-2 flex items-center gap-2"><mdi-lock-check class="inline-block" /> RTSP over TLS</div>
  <div class="dim">RTSPS encrypts the channel — the proxy can no longer read or rewrite the stream.</div>
</div>

<div class="card">
  <div class="accent font-bold mb-2 flex items-center gap-2"><mdi-chart-line class="inline-block" /> ARP / network monitoring</div>
  <div class="dim">Flag anomalous ARP table changes. Tooling: arpwatch, NDR/XDR.</div>
</div>

</v-clicks>

</div>

<!--
Land this constructively — after the demo, the room's attention is on "how
exposed am I," so this is the slide that actually earns its place. Don't
rush it just because it feels like a formality.

The DAI bullet is a deliberate callback to the field story: assuming a
control is enforced isn't the same as confirming it is — that gap is the
actual lesson from testing against a network believed to have DAI on.
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
<div class="mt-6 text-center warn text-lg italic">
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
transition: zoom-out
class: text-center end
---

# RTSPoofing
## *Trust Me, I'm a Camera* <mdi-cctv class="inline-block ml-1" />

<div class="mt-8 dim">
Code available after the talk, for research and authorized testing.<br/>
Please use it responsibly — and get written authorization first.
</div>

<div class="mt-8 text-sm dim">
<span class="inline-flex items-center gap-1"><mdi-alert class="warn inline-block" /> This talk is for educational purposes.</span><br/>
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
- "Does this work over UDP transport, not just TCP-interleaved?" — yes,
  out of scope for this cut of the talk; RTSPoofing rewrites the SETUP
  negotiation the same way, one layer up, and uses four sockets per track
  to satisfy NAT/source-port validation on both sides.
- "Have vendors been notified?" — answer honestly based on your actual
  disclosure status; don't overstate coordination that didn't happen.
- Where to get the code / how to reach you — have the repo URL and contact
  info ready to say out loud, not just on a slide people can't photograph
  in time.
-->
