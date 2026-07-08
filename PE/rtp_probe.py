#!/usr/bin/env python3
"""
rtp_probe.py — Análisis en tiempo real de parámetros RTP desde el stream interceptado.
Se integra con RTSPoofing.py para extraer PT, SSRC, framerate, resolución y codec
automáticamente durante el warm-up, antes de iniciar la inyección.
"""

import struct
import time
import logging
from collections import defaultdict
from typing import Optional

log = logging.getLogger("probe")


# ─────────────────────────────────────────────
# Constantes de Payload Types conocidos
# ─────────────────────────────────────────────

PT_NAMES = {
    26: "MJPEG",
    33: "MP2T",
    96: "H264/H265 (dinámico)",
    97: "H264/H265 (dinámico)",
    98: "H264/H265 (dinámico)",
    99: "H264/H265 (dinámico)",
}

NAL_TYPES_H264 = {
    1: "Non-IDR slice",
    5: "IDR (keyframe)",
    6: "SEI",
    7: "SPS",
    8: "PPS",
    24: "STAP-A",
    28: "FU-A (fragmented)",
}

NAL_TYPES_H265 = {
    19: "IDR_W_RADL",
    20: "IDR_N_LP",
    32: "VPS",
    33: "SPS",
    34: "PPS",
    39: "PREFIX_SEI",
    49: "FU (fragmented)",
}


# ─────────────────────────────────────────────
# Parser de cabecera RTP
# ─────────────────────────────────────────────

def parse_rtp_header(data: bytes) -> Optional[dict]:
    if len(data) < 12:
        return None
    if (data[0] >> 6) != 2:
        return None

    flags   = data[0]
    pt_byte = data[1]
    seq     = struct.unpack("!H", data[2:4])[0]
    ts      = struct.unpack("!I", data[4:8])[0]
    ssrc    = struct.unpack("!I", data[8:12])[0]

    marker  = bool(pt_byte & 0x80)
    pt      = pt_byte & 0x7F
    cc      = flags & 0x0F          # CSRC count
    has_ext = bool(flags & 0x10)

    # Calcula el offset real del payload (saltando CSRCs y extensión)
    payload_offset = 12 + cc * 4
    if has_ext and len(data) >= payload_offset + 4:
        ext_len = struct.unpack("!H", data[payload_offset + 2: payload_offset + 4])[0]
        payload_offset += 4 + ext_len * 4

    payload = data[payload_offset:] if len(data) > payload_offset else b""

    return {
        "pt": pt,
        "seq": seq,
        "ts": ts,
        "ssrc": ssrc,
        "marker": marker,
        "payload": payload,
        "raw": data,
    }


# ─────────────────────────────────────────────
# Detección de codec desde NAL units
# ─────────────────────────────────────────────

def detect_codec_from_payload(payload: bytes) -> Optional[str]:
    """
    Intenta determinar si el payload es H.264 o H.265 mirando el tipo NAL.
    Funciona con FU-A (fragmentado) y paquetes single NAL.
    """
    if len(payload) < 2:
        return None

    nal_byte = payload[0]

    # H.264: bits 5-1 del primer byte son el nal_unit_type
    nal_h264 = nal_byte & 0x1F
    # H.265: bits 9-1 de los dos primeros bytes son el nal_unit_type
    nal_h265 = (nal_byte >> 1) & 0x3F

    if nal_h264 in NAL_TYPES_H264:
        return "H264"
    if nal_h265 in NAL_TYPES_H265:
        return "H265"

    # FU-A H.264 (nal_type == 28): el segundo byte tiene el tipo real
    if nal_h264 == 28 and len(payload) >= 2:
        fu_nal = payload[1] & 0x1F
        if fu_nal in NAL_TYPES_H264:
            return "H264"

    # FU H.265 (nal_type == 49)
    if nal_h265 == 49 and len(payload) >= 3:
        fu_nal = payload[2] & 0x3F
        if fu_nal in NAL_TYPES_H265:
            return "H265"

    return None


# ─────────────────────────────────────────────
# Extracción de resolución desde SPS H.264
# ─────────────────────────────────────────────

def try_extract_resolution_h264(payload: bytes) -> Optional[tuple]:
    """
    Extrae resolución desde un NAL SPS H.264 (tipo 7).
    Parsing mínimo — suficiente para width/height sin implementar
    el Exp-Golomb completo.
    """
    if len(payload) < 4:
        return None

    nal_type = payload[0] & 0x1F
    if nal_type != 7:  # SPS
        return None

    # Bytes 1-3: profile_idc, flags, level_idc
    # A partir del byte 4 empieza el parsing Exp-Golomb — complejo.
    # En su lugar extraemos de forma heurística buscando patrones comunes.
    # Para una PoC, basta con loguear que tenemos un SPS y dejar la resolución
    # a lo que negocia el SDP.
    log.info("[SPS H264 detectado] profile_idc=%d level=%d", payload[1], payload[3])
    return None  # Extend here if full SPS parsing is needed


# ─────────────────────────────────────────────
# Clase principal: RTPProbe
# ─────────────────────────────────────────────

class RTPProbe:
    """
    Analiza frames RTP en tiempo real durante el warm-up.
    Llama a .feed(channel, rtp_payload) por cada frame que recibe el MITM.
    Cuando tiene suficiente información, .ready() devuelve True y
    .params() devuelve los parámetros detectados.
    """

    def __init__(self, probe_duration: float = 3.0, min_frames: int = 30):
        self.probe_duration = probe_duration
        self.min_frames     = min_frames
        self._start         = time.monotonic()

        # Contadores
        self._pt_counts     = defaultdict(int)
        self._ssrc_counts   = defaultdict(int)
        self._channel_counts= defaultdict(int)
        self._codec_votes   = defaultdict(int)

        # Secuencias para calcular framerate
        self._timestamps    = []   # (monotonic_time, rtp_ts)
        self._seq_numbers   = []
        self._last_seq      = None
        self._gaps          = 0
        self._total_frames  = 0

        # Resultado
        self._result        = None

    def feed(self, channel: int, rtp_payload: bytes):
        hdr = parse_rtp_header(rtp_payload)
        if not hdr:
            return

        now = time.monotonic()
        self._total_frames += 1
        self._channel_counts[channel] += 1
        self._pt_counts[hdr["pt"]] += 1
        self._ssrc_counts[hdr["ssrc"]] += 1
        self._timestamps.append((now, hdr["ts"]))

        # Detección de gaps en secuencia
        if self._last_seq is not None:
            expected = (self._last_seq + 1) & 0xFFFF
            if hdr["seq"] != expected:
                self._gaps += 1
        self._last_seq = hdr["seq"]

        # Intento de detección de codec
        codec = detect_codec_from_payload(hdr["payload"])
        if codec:
            self._codec_votes[codec] += 1

        # SPS detection para H264
        if hdr["payload"] and (hdr["payload"][0] & 0x1F) == 7:
            try_extract_resolution_h264(hdr["payload"])

        # Si ya tenemos resultado, actualiza timestamps para framerate más preciso
        if self._result:
            return

        # ¿Tenemos suficiente para decidir?
        elapsed = now - self._start
        if elapsed >= self.probe_duration and self._total_frames >= self.min_frames:
            self._result = self._compute()
            self._print_result()

    def ready(self) -> bool:
        return self._result is not None

    def params(self) -> Optional[dict]:
        return self._result

    def force_result(self) -> dict:
        """Fuerza el cálculo aunque no haya pasado el tiempo mínimo."""
        if not self._result:
            self._result = self._compute()
            self._print_result()
        return self._result

    def _compute(self) -> dict:
        # PT dominante
        pt = max(self._pt_counts, key=self._pt_counts.get) if self._pt_counts else None

        # SSRC dominante
        ssrc = max(self._ssrc_counts, key=self._ssrc_counts.get) if self._ssrc_counts else None

        # Canal dominante
        channel = max(self._channel_counts, key=self._channel_counts.get) if self._channel_counts else 0

        # Codec más votado
        codec = max(self._codec_votes, key=self._codec_votes.get) if self._codec_votes else "H264"

        # Framerate: estimado desde timestamps RTP (clock = 90000 Hz para vídeo)
        fps = self._estimate_fps()

        return {
            "pt": pt,
            "ssrc": ssrc,
            "ssrc_hex": f"0x{ssrc:08x}" if ssrc else None,
            "channel": channel,
            "codec": codec,
            "fps": fps,
            "total_frames": self._total_frames,
            "gaps": self._gaps,
            "pt_distribution": dict(self._pt_counts),
            "ssrc_distribution": {f"0x{k:08x}": v for k, v in self._ssrc_counts.items()},
        }

    def _estimate_fps(self) -> Optional[float]:
        """
        Estima FPS a partir de la diferencia de timestamps RTP.
        Clock de vídeo estándar: 90000 Hz.
        """
        if len(self._timestamps) < 10:
            return None

        # Usa solo los últimos N pares para estabilidad
        samples = self._timestamps[-60:]
        rtp_clock = 90000

        ts_diffs = []
        for i in range(1, len(samples)):
            wall_dt = samples[i][0] - samples[i-1][0]
            rtp_dt  = (samples[i][1] - samples[i-1][1]) & 0xFFFFFFFF

            # Filtra saltos grandes (probablemente marker bits o gaps)
            if rtp_dt == 0 or rtp_dt > rtp_clock:
                continue
            if wall_dt < 0.0001:
                continue

            fps_sample = rtp_clock / rtp_dt
            if 1.0 < fps_sample < 120.0:
                ts_diffs.append(fps_sample)

        if not ts_diffs:
            return None

        # Mediana para robustez ante outliers
        ts_diffs.sort()
        mid = len(ts_diffs) // 2
        return round(ts_diffs[mid], 2)

    def _print_result(self):
        r = self._result
        log.info("=" * 55)
        log.info("  RTPProbe — parámetros detectados automáticamente")
        log.info("=" * 55)
        log.info("  PT (Payload Type) : %s  %s", r["pt"], PT_NAMES.get(r["pt"], ""))
        log.info("  SSRC              : %s", r["ssrc_hex"])
        log.info("  Canal interleaved : %s", r["channel"])
        log.info("  Codec detectado   : %s", r["codec"])
        log.info("  FPS estimado      : %s", r["fps"])
        log.info("  Frames analizados : %s  (gaps: %s)", r["total_frames"], r["gaps"])
        log.info("  PT dist.          : %s", r["pt_distribution"])
        log.info("=" * 55)
