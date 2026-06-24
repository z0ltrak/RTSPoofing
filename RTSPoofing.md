---
theme: default
background: '#0a0a0a'
class: text-center
highlighter: shiki
lineNumbers: false
transition: slide-left
mdc: true
fonts:
  sans: 'JetBrains Mono'
  mono: 'JetBrains Mono'
---

# RTSPoofing
## *Trust Me, I'm a Camera* 🎥

<div class="mt-8 text-gray-400 text-xl">
Cómo convencer a un NVR de que eres una cámara legítima<br/>cuando claramente no lo eres
</div>

<div class="mt-12 text-sm text-gray-600">
⚠️ Con fines educativos. Probablemente.
</div>

---
layout: center
transition: fade
---

# ¿Quién tiene cámaras IP en su red?


<v-click>
<div class="mt-8 text-2xl text-green-400 text-center">
¿Y quién sabe exactamente qué tráfico mandan?
</div>
<div class="mt-6 flex justify-center">
  <img src="/gifs/cat-stare.gif" class="rounded-lg" style="height:160px"/>
</div>
</v-click>

---
layout: center
transition: zoom-out
---

# El problema con las cámaras IP

<div class="grid grid-cols-2 gap-12 mt-8 text-left">
<div>

### Lo que piensas que pasa
```
📷 Cámara → 🖥️ NVR
```
<div class="mt-4 text-gray-400">
Bonito. Simple. Seguro.
</div>

</div>
<div v-click>

### Lo que realmente pasa
```
📷 Cámara → 🦹 Tú → 🖥️ NVR
```
<div class="mt-4 text-red-400">
No tan bonito. No tan simple.<br/>
Definitivamente no tan seguro.
</div>

</div>
</div>

---
layout: center
transition: slide-left
---

# ¿Qué es RTSP?

<div class="text-left max-w-2xl mx-auto mt-4">

**Real Time Streaming Protocol** — el HTTP del vídeo vigilancia

```
DESCRIBE rtsp://192.168.1.64/stream RTSP/1.0
↓
200 OK — aquí tienes el SDP con los parámetros del stream

SETUP rtsp://192.168.1.64/stream/track1 RTSP/1.0
↓
200 OK — canal TCP interleaved asignado

PLAY rtsp://192.168.1.64/stream RTSP/1.0
↓
💥 Aquí empieza el caos
```

</div>

<v-click>
<div class="mt-4 text-center text-yellow-400 text-lg">
Todo esto en texto plano. Sin cifrado. Sin autenticación obligatoria.<br/>
En el 90% de las instalaciones.
</div>
</v-click>

---
layout: default
transition: fade
---

# Anatomía del paquete RTP

<div class="text-left max-w-2xl mx-auto mt-2 font-mono text-sm">

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       Sequence Number         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Synchronization Source (SSRC) identifier           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    💣 Tu vídeo aquí 💣                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

</div>

<v-click>
<div class="mt-4 grid grid-cols-3 gap-4 text-center text-sm">
  <div class="bg-blue-900 rounded p-3">
    <div class="text-blue-300 font-bold">Sequence Number</div>
    <div class="text-gray-400 mt-1">Orden de los frames.<br/>Hay que mantenerlo.</div>
  </div>
  <div class="bg-green-900 rounded p-3">
    <div class="text-green-300 font-bold">Timestamp</div>
    <div class="text-gray-400 mt-1">Clock a 90000 Hz.<br/>Hay que continuarlo.</div>
  </div>
  <div class="bg-red-900 rounded p-3">
    <div class="text-red-300 font-bold">SSRC</div>
    <div class="text-gray-400 mt-1">ID del emisor.<br/>Hay que suplantarlo.</div>
  </div>
</div>
</v-click>

---
layout: center
transition: slide-up
---

# El ataque en 3 pasos

<div class="mt-6">
<v-clicks>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="w-12 h-12 bg-red-600 rounded-full flex items-center justify-center font-bold text-2xl flex-shrink-0">1</div>
  <div><span class="text-red-400 font-bold">ARP Spoofing</span> — convencer a la red de que somos la cámara</div>
</div>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="w-12 h-12 bg-yellow-600 rounded-full flex items-center justify-center font-bold text-2xl flex-shrink-0">2</div>
  <div><span class="text-yellow-400 font-bold">MITM Proxy</span> — interceptar y relayar el stream RTSP/RTP</div>
</div>

<div class="flex items-center gap-4 mb-5 text-xl">
  <div class="w-12 h-12 bg-green-600 rounded-full flex items-center justify-center font-bold text-2xl flex-shrink-0">3</div>
  <div><span class="text-green-400 font-bold">Frame Injection</span> — sustituir los frames reales por los nuestros</div>
</div>

</v-clicks>
</div>

<v-click>
<div class="mt-6 text-center text-gray-400 italic">
  Todo esto mientras el NVR sigue feliz grabando lo que le mandamos.
</div>
</v-click>

---
layout: center
transition: zoom-out
---

# Paso 1: ARP Spoofing

<div class="grid grid-cols-2 gap-8 mt-4 text-left">
<div>

**El problema:**
La cámara y el NVR hablan directamente.
Nosotros no existimos para ellos.

**La solución:**
Envenenar las tablas ARP de ambos.

```bash
arpspoof -i eth0 -t <NVR> <CAM>
arpspoof -i eth0 -t <CAM> <NVR>
```

Ahora ambos creen que somos el otro. 😈

</div>
<div v-click>

**El resultado:**
```
📷 Cámara
    ↓ "Aquí está el NVR (MAC: nosotros)"
🦹 Kali MITM
    ↓ "Aquí está la Cámara (MAC: nosotros)"
🖥️ NVR
```

El tráfico pasa por nosotros.<br/>
Nadie se da cuenta.

</div>
</div>

<v-click>
<div class="mt-4 text-center text-sm text-gray-500">
⚠️ En redes con Dynamic ARP Inspection (DAI) esto no funciona.<br/>
Que es exactamente lo que tiene el Forti. Gracias, Forti. 🙃
</div>
</v-click>

---
layout: center
transition: slide-left
---

# ¿Que hacemos entonces?



<v-click>
<div class="mt-9 text-center text-xl text-gray-300">
  Solución: conectar la víctima al proxy <span class="text-green-400 font-bold">manualmente</span>.<br/>
</div>
<div class="text-center">
  <span class="text-gray-500 text-base mt-2 block">Para la demo funciona igual de bien. Y no me voy a arriesgar a que nos llamen otra vez del SOC.</span>
</div>
</v-click>

<v-click>
  <div class="flex justify-center mt-4">
  <img src="/gifs/SOC.jpg" class="rounded-lg" style="height:220px"/>
  </div>
</v-click>

---
layout: default
transition: fade
---

# Paso 2: El Proxy MITM

<div class="mt-8 text-center">
  El proxy hace <strong>tres cosas simultáneamente</strong>:
</div>


<div class="mt-10 grid grid-cols-3 gap-6">

  <!-- Columna 1 -->
  <v-click>
  <div>
    <div class="text-5xl mb-4">①</div>
    <div class="font-bold text-xl mb-3 text-blue-400">Negociación RTSP transparente</div>
    <ul class="text-sm space-y-2 text-left">
      <li>• Intercepta <code>DESCRIBE</code>, <code>SETUP</code>, <code>PLAY</code></li>
      <li>• Reenvía a la cámara real</li>
      <li>• Devuelve respuestas al NVR sin modificar</li>
      <li class="text-green-400 font-medium">→ El NVR no detecta intermediario</li>
    </ul>
  </div>
  </v-click>

  <!-- Columna 2 -->
  <v-click>
  <div>
    <div class="text-5xl mb-4">②</div>
    <div class="font-bold text-xl mb-3 text-blue-400">RTP Probe automático</div>
    <ul class="text-sm space-y-2 text-left">
      <li>• Analiza los primeros frames en tiempo real</li>
      <li>• Detecta: PT, SSRC, codec (H264/H265), FPS</li>
      <li class="text-green-400 font-medium">→ Sin configuración manual</li>
    </ul>
  </div>
  </v-click>

  <!-- Columna 3 -->
  <v-click>
  <div>
    <div class="text-5xl mb-4">③</div>
    <div class="font-bold text-xl mb-3 text-blue-400">Canal de inyección</div>
    <ul class="text-sm space-y-2 text-left">
      <li>• Mientras el stream fluye normalmente...</li>
      <li>• En el momento elegido, sustituye los frames</li>
      <li>• Reescribe seq numbers y timestamps</li>
      <li class="text-green-400 font-medium">→ Para mantener continuidad</li>
    </ul>
  </div>
  </v-click>

</div>

---
layout: center
transition: slide-up
---

# RTPProbe: Autodetección en tiempo real

<div class="text-left max-w-2xl mx-auto mt-4 text-sm">

Durante los primeros segundos el proxy **solo escucha**:

```
[00:00.0] 🔍 Analizando stream...
[00:01.2] PT=96 visto 847 veces → H264 dinámico
[00:02.1] SSRC=0xDEAD1234 dominante (99.8% de frames)
[00:02.8] FPS estimado: 25.0 Hz (via diff timestamps RTP)
[00:03.0] Codec: H264 (FU-A fragmentado detectado)
[00:03.0] ✅ Probe completo — iniciando inyección
```

</div>

<v-click>
<div class="mt-4 bg-gray-900 rounded-lg p-4 text-center">
<div class="text-green-400 font-bold text-lg">¿Cómo detecta el FPS sin metadatos?</div>
<div class="text-gray-300 mt-2">
Clock RTP estándar para vídeo = 90.000 Hz<br/>
Si entre dos frames hay 3.600 ticks → 90000/3600 = <span class="text-yellow-400 font-bold">25 fps</span>
</div>
</div>
</v-click>

---
layout: center
transition: slide-left
---

# Paso 3: Frame Injection

<div class="text-left max-w-2xl mx-auto mt-4">

Una vez el probe tiene los parámetros, el injector:

<v-clicks>

**① Lee frames pre-grabados** del archivo `.rtp`
- Capturado previamente de la misma cámara
- O generado desde cualquier vídeo con ffmpeg

**② Reescribe cada frame RTP:**
```python
# Mantiene continuidad con el stream anterior
seq  = (last_live_seq + frame_index + 1) & 0xFFFF
ts   = (last_live_ts + frame_index * ts_increment) & 0xFFFFFFFF
ssrc = detected_ssrc  # mismo SSRC que la cámara real
```

**③ El NVR recibe frames perfectamente válidos**
- Misma secuencia numérica → sin saltos
- Mismo SSRC → mismo "emisor"
- Timestamps continuos → sin glitches

</v-clicks>

</div>

---
layout: center
transition: zoom-out
---

# Lo que ve el NVR

<div class="grid grid-cols-2 gap-8 mt-6 text-center">
<div class="bg-gray-900 rounded-lg p-6">
  <div class="text-4xl mb-3">🎬</div>
  <div class="text-green-400 font-bold text-lg">Stream real</div>
  <div class="text-gray-400 mt-2 text-sm">Cámara apuntando al parking vacío<br/>a las 3 AM</div>
</div>
<div v-click class="bg-gray-900 rounded-lg p-6">
  <div class="text-4xl mb-3">🎭</div>
  <div class="text-red-400 font-bold text-lg">Stream inyectado</div>
  <div class="text-gray-400 mt-2 text-sm">Grabación en bucle del mismo<br/>parking vacío de ayer</div>
</div>
</div>

<v-click>
<div class="mt-6 text-2xl text-yellow-400 text-center">
  Para el NVR: indistinguible.
</div>
<div class="text-gray-400 mt-1 text-center">
  Mismo protocolo. Mismos parámetros. Misma fuente.
</div>
</v-click>

---
layout: center
transition: fade
---

# El NVR grabando nuestro vídeo

<div class="flex justify-center mt-4">
  <img src="/gifs/cat-happy.gif" class="rounded-lg" style="height:220px"/>
</div>

<div class="mt-6 text-center text-xl text-gray-300">
  El NVR: <span class="text-green-400">"Todo normal por aquí. Grabando. Sin novedad."</span>
</div>

---
layout: center
transition: slide-up
---

# ¿Qué pasa si la conexión ya está establecida?

<div class="text-xl mt-4 text-gray-300 text-center">
  El NVR ya está conectado a la cámara cuando arrancas el proxy.<br/>
  Tu proxy escucha en el puerto 554 pero nadie conecta.
</div>

<v-click>
<div class="mt-6 bg-gray-900 rounded-lg p-5 text-left max-w-xl mx-auto">

**Solución: `tcpkill`**

```bash
# Rompe la sesión TCP existente
tcpkill -9 -i eth0 host 192.168.1.64 and port 554
```

El NVR detecta la desconexión → reconecta solo → esta vez pasa por el proxy.

</div>
</v-click>


---
layout: center
transition: slide-left
---

# Falsificando la hora

<div class="mt-4 text-gray-300 text-lg text-center">
Las cámaras mandan dos tipos de timestamps:
</div>

<div class="grid grid-cols-2 gap-6 mt-4 text-left text-sm">
<div class="bg-gray-900 rounded p-4">
  <div class="text-blue-400 font-bold mb-2">RTP Timestamps</div>
  <div class="text-gray-400">Clock a 90000 Hz para sincronización A/V.<br/>
  <span class="text-green-400">✅ Ya los reescribimos.</span></div>
</div>
<div class="bg-gray-900 rounded p-4">
  <div class="text-red-400 font-bold mb-2">RTCP Sender Reports</div>
  <div class="text-gray-400">NTP wall-clock real.<br/>
  El NVR los usa para saber la hora exacta del vídeo.<br/>
  <span class="text-yellow-400">⚠️ Hay que reescribirlos también.</span></div>
</div>
</div>

<v-click>
<div class="mt-4 bg-gray-900 rounded p-4 text-left text-sm max-w-xl mx-auto">

```
RTCP Sender Report (PT=200):
  bytes 0-7:  header + SSRC
  bytes 8-11: NTP seconds    ← 🎯 aquí está la hora real
  bytes 12-15: NTP fraction  ← 🎯 y aquí
  bytes 16+:  RTP timestamp
```

Reescribimos esos 8 bytes con la hora que queramos. ✅

</div>
</v-click>

---
layout: center
transition: zoom-out
---

# Entornos donde funciona

<div class="mt-4 grid grid-cols-3 gap-4 text-center text-sm">

<v-clicks>

<div class="bg-green-900 rounded-lg p-4">
  <div class="text-3xl mb-2">🏠</div>
  <div class="text-green-400 font-bold">Particulares</div>
  <div class="text-gray-300 mt-2">Router doméstico sin DAI.<br/>ARP spoof funciona siempre.</div>
  <div class="text-green-400 mt-2 font-bold text-lg">~100%</div>
</div>

<div class="bg-yellow-900 rounded-lg p-4">
  <div class="text-3xl mb-2">🏪</div>
  <div class="text-yellow-400 font-bold">Pequeña empresa</div>
  <div class="text-gray-300 mt-2">Switch no gestionable.<br/>Sin hardening de red.</div>
  <div class="text-yellow-400 mt-2 font-bold text-lg">~90%</div>
</div>

<div class="bg-orange-900 rounded-lg p-4">
  <div class="text-3xl mb-2">📹</div>
  <div class="text-orange-400 font-bold">CCTV / NVR dedicado</div>
  <div class="text-gray-300 mt-2">Red plana, Hikvision/Dahua.<br/>Instaladores sin formación.</div>
  <div class="text-orange-400 mt-2 font-bold text-lg">~85%</div>
</div>

</v-clicks>

</div>

<v-click>
<div class="mt-4 bg-red-950 rounded-lg p-3 text-center text-sm">
  <span class="text-red-400 font-bold">Donde NO funciona ARP spoof:</span>
  <span class="text-gray-300 ml-2">Redes corporativas con DAI — como con el maldito Forti</span>
</div>
</v-click>

---
layout: center
transition: fade
---

# Arquitectura completa

<div class="text-left max-w-2xl mx-auto mt-4 font-mono text-sm">

```
┌─────────────┐         ┌──────────────────────┐         ┌─────────┐
│   IP Cam    │────────▶│    Kali MITM (tú)    │────────▶│   NVR   │
│             │◀────────│                      │◀────────│         │
└─────────────┘  TCP    │  ┌────────────────┐  │  TCP    └─────────┘
                 RTSP   │  │  RTSP Proxy    │  │  RTSP
                 RTP    │  │  RTPProbe      │  │  RTP
                        │  │  Frame Inject  │  │  (modificado)
                        │  └────────────────┘  │
                        └──────────────────────┘
                                  ↑
                        ARP Spoof activo:
                        CAM cree que NVR = Kali
                        NVR cree que CAM = Kali
```

</div>

---
layout: center
transition: slide-left
---

# Demo

<div class="flex justify-center mt-4">
  <img src="C:\Users\marti\Desktop\RTSPoofing\RTSPoofingTalk\gifs\let-it.gif" class="rounded-lg" style="height:250px"/>
</div>


---
layout: center
transition: zoom-out
---

# ¿Cómo me protejo?

<div class="mt-4 grid grid-cols-2 gap-5 text-left text-sm max-w-2xl mx-auto">

<v-clicks>

<div class="bg-gray-900 rounded-lg p-4">
  <div class="text-blue-400 font-bold mb-2">🔒 VLAN dedicada para cámaras</div>
  <div class="text-gray-400">Aislar el tráfico de videovigilancia del resto de la red.</div>
</div>

<div class="bg-gray-900 rounded-lg p-4">
  <div class="text-blue-400 font-bold mb-2">🛡️ Dynamic ARP Inspection</div>
  <div class="text-gray-400">Switches gestionables con DAI activo. Bloquea el ARP spoof en origen.</div>
</div>

<div class="bg-gray-900 rounded-lg p-4">
  <div class="text-blue-400 font-bold mb-2">🔐 RTSP sobre TLS</div>
  <div class="text-gray-400">RTSPS cifra el canal. El proxy no puede leer ni modificar el stream.</div>
</div>

<div class="bg-gray-900 rounded-lg p-4">
  <div class="text-blue-400 font-bold mb-2">📊 Monitorización de ARP</div>
  <div class="text-gray-400">Detectar cambios anómalos en tablas ARP. Herramientas: arpwatch, XDR.</div>
</div>

</v-clicks>

</div>

---
layout: center
transition: slide-up
---

# Conclusiones

<div class="mt-6 text-left max-w-xl mx-auto">

<v-clicks>

- Las cámaras IP confían **ciegamente** en quien les habla por TCP
- RTSP/RTP no tiene mecanismos de autenticación del stream
- El ataque funciona **sin tocar la cámara ni el NVR**
- La detección es **casi imposible** desde el NVR sin monitorización de red
- El 85-95% de instalaciones domésticas y PYMES son vulnerables **hoy**

</v-clicks>

</div>

<v-click>
<div class="mt-6 text-center text-yellow-400 text-lg italic">
"Si tu sistema de seguridad puede ser engañado<br/>
por un script de Python de 700 líneas...<br/>
quizás no es tan seguro."
</div>
</v-click>

---
layout: center
transition: fade
---

# Una última reflexión
<v-click>
<div class="flex justify-center mt-4">
  <img src="C:\Users\marti\Desktop\RTSPoofing\RTSPoofingTalk\gifs\ооо.gif" class="rounded-lg" style="height:180px"/>
</div>


<div class="mt-6 bg-gray-900 rounded-xl p-6 max-w-2xl mx-auto text-center">
  <div class="text-gray-500 text-sm mb-3">— Midnight Blue, sobre firmware de cámaras Dahua</div>
  <div class="text-white text-xl italic leading-relaxed">
    "Since it is all code written by Dahua,<br/>
    <span class="text-red-400 font-bold">there must be a parsing bug somewhere.</span>"
  </div>
</div>
</v-click>

<v-click>
<div class="mt-4 text-center text-gray-500 text-sm">
  Spoiler: había varios.
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
Código disponible tras la charla.<br/>
Úsalo con responsabilidad. O no. Pero que no te pillen.
</div>

<div class="mt-8 text-sm text-gray-600">
⚠️ Esta charla es con fines educativos.<br/>
Testar en redes ajenas sin autorización es ilegal.<br/>
No me hago responsable de lo que hagáis con esto.
</div>

<div class="mt-8 text-3xl">
<v-click>¿Preguntas?</v-click> <v-click>¿Donaciones?</v-click> <v-click>¿Denuncias?</v-click>
</div>
