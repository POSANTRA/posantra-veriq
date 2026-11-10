"""POSANTRA | VERIQ - pixel forensics (numpy only, works on compressed copies).

Rule-of-thumb signals read from the pixels of a central crop. They are WEAK
clues: WhatsApp-style compression erases evidence, beauty filters can look
AI-like, and the thresholds are not calibrated on a validated data set. They
never prove anything and never say an image is real.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional

import numpy as np
from PIL import Image

import config

AI, CAMERA, NEUTRAL = "ai", "camera", "neutral"
LEANS_AI, CAMERA_LIKE, MIXED, UNCLEAR = "leans_ai", "camera_like", "mixed", "unclear"
CROP = 512
TILE = 16
MIN_SIDE = 96


@dataclass
class Signal:
    name: str
    icon: str
    lean: str
    note: str


@dataclass
class PixelReport:
    status: str
    level: str = UNCLEAR
    signals: list = field(default_factory=list)
    ai_count: int = 0
    camera_count: int = 0
    reliability: str = "medium"
    notes: list = field(default_factory=list)
    error: Optional[str] = None


def _load(data: bytes):
    with Image.open(BytesIO(data)) as img:
        w, h = img.size
        rgb = img.convert("RGB")
    cw, ch = min(w, CROP) // 8 * 8, min(h, CROP) // 8 * 8
    x0, y0 = ((w - cw) // 2) // 8 * 8, ((h - ch) // 2) // 8 * 8
    arr = np.asarray(rgb.crop((x0, y0, x0 + cw, y0 + ch)), dtype=np.float32)
    gray = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    return gray, w, h


def _blur3(a):
    p = np.pad(a, 1, mode="edge")
    h, w = a.shape
    return sum(p[i:i + h, j:j + w] for i in range(3) for j in range(3)) / 9.0


def _tiles(a):
    h, w = a.shape
    h2, w2 = h // TILE * TILE, w // TILE * TILE
    return a[:h2, :w2].reshape(h2 // TILE, TILE, w2 // TILE, TILE).swapaxes(1, 2).reshape(-1, TILE, TILE)


def _noise(g):
    blur = _blur3(g)
    rt, bt, gt = _tiles(g - blur), _tiles(blur), _tiles(g)
    grad = np.abs(np.diff(bt, axis=2)).mean(axis=(1, 2)) + np.abs(np.diff(bt, axis=1)).mean(axis=(1, 2))
    sd, br = rt.std(axis=(1, 2)), gt.mean(axis=(1, 2))
    k = max(8, int(len(grad) * 0.4))
    idx = np.argsort(grad)[:k]
    flat_sd, flat_br = sd[idx], br[idx]
    noise = float(np.median(flat_sd))
    dep = None
    if len(idx) >= 16:
        med = np.median(flat_br)
        dark, bright = flat_sd[flat_br <= med], flat_sd[flat_br > med]
        if len(dark) >= 6 and len(bright) >= 6 and np.median(dark) > 0.05:
            dep = float(np.median(bright) / np.median(dark))
    return noise, dep


def _spectrum(g):
    n = min(g.shape) // 2 * 2
    s = g[:n, :n] - g[:n, :n].mean()
    win = np.outer(np.hanning(n), np.hanning(n))
    p = np.abs(np.fft.fftshift(np.fft.fft2(s * win))) ** 2
    yy, xx = np.indices(p.shape)
    c = n / 2
    r = np.hypot(yy - c, xx - c) / c
    mid = p[(r > 0.08) & (r <= 0.5)].sum()
    high = p[(r > 0.5) & (r <= 1.0)].sum()
    hf = float(high / (mid + 1e-9))
    lg = np.log1p(np.sqrt(p))
    ring = (r > 0.3) & (r <= 0.95) & (np.abs(yy - c) > 3) & (np.abs(xx - c) > 3)
    v = lg[ring]
    z = float((v.max() - np.median(v)) / (v.std() + 1e-6))
    return hf, z


def _blockiness(g):
    d = np.abs(np.diff(g, axis=1)).mean(axis=0)
    if len(d) < 16:
        return 1.0
    edge = d[7::8].mean()
    other = np.delete(d, np.arange(7, len(d), 8)).mean()
    return float(edge / (other + 1e-6))


def analyze(data: bytes, kind_key: str = "") -> PixelReport:
    """Never raises. kind_key='screenshot' stops flat screen colours counting as 'too clean'."""
    try:
        g, w, h = _load(data)
    except Exception as exc:
        return PixelReport(config.STATUS_FAILED, error=f"The pixels could not be read ({type(exc).__name__}).")
    if min(g.shape) < MIN_SIDE:
        return PixelReport(config.STATUS_NOT_AVAILABLE, error="The picture is too small for pixel checks.")
    try:
        noise, dep = _noise(g)
        hf, z = _spectrum(g)
        block = _blockiness(g)
    except Exception as exc:
        return PixelReport(config.STATUS_FAILED, error=f"Pixel checks failed ({type(exc).__name__}).")

    shot = kind_key == "screenshot"
    heavy = block > 1.12
    sig: list = []

    if shot:
        sig.append(Signal("Grain level", "🌾", NEUTRAL, "Screenshots contain flat screen colours, so grain is not judged."))
    elif noise < 0.8:
        sig.append(Signal("Grain level", "🌾", AI, "Pixels are very clean, with almost no sensor-like grain."))
    elif noise > 2.0:
        sig.append(Signal("Grain level", "🌾", CAMERA, "Grain-like noise is present, as in camera photos (compression can add it too)."))
    else:
        sig.append(Signal("Grain level", "🌾", NEUTRAL, "A moderate amount of grain."))

    if dep is not None and not shot and dep >= 1.15:
        sig.append(Signal("Sensor-like noise", "📡", CAMERA, "Noise grows with brightness, which is how camera sensors behave."))
    else:
        sig.append(Signal("Sensor-like noise", "📡", NEUTRAL, "No sensor-like noise pattern was seen."))

    if hf < 0.0015:
        sig.append(Signal("Fine detail", "🔎", AI, "Very little fine detail: the picture may be AI-smoothed, upscaled or beautified."))
    else:
        sig.append(Signal("Fine detail", "🔎", NEUTRAL, "Normal amount of fine detail."))

    if hf < 0.0015:
        enh = "Looks smoothed or upscaled (an enhancement or beauty app, or a resize, can cause this)."
    elif hf > 0.3:
        enh = "Looks over-sharpened or very crunchy (a sharpening or HDR app can cause this)."
    else:
        enh = "No strong sign of sharpening or upscaling."
    sig.append(Signal("Enhancement check", "✨", NEUTRAL, enh))

    if z > 12 and not heavy:
        sig.append(Signal("Repeating pattern", "🧩", AI, "A regular grid-like pattern in fine detail, sometimes left by AI upscaling layers."))
    else:
        sig.append(Signal("Repeating pattern", "🧩", NEUTRAL, "No repeating fine pattern."))

    if min(w, h) >= 512 and w % 64 == 0 and h % 64 == 0:
        sig.append(Signal("Picture size", "📐", AI, f"{w}x{h} px is a size many AI tools produce (apps like WhatsApp resize pictures, which hides this)."))
    else:
        sig.append(Signal("Picture size", "📐", NEUTRAL, f"{w}x{h} px is not a typical AI-tool size."))

    sig.append(Signal("Compression", "🗜️", NEUTRAL,
                      "Strong JPEG compression found, typical of WhatsApp and social apps. It hides evidence, so the other checks are less reliable."
                      if heavy else "No strong compression pattern."))

    ai_n = sum(s.lean == AI for s in sig)
    cam_n = sum(s.lean == CAMERA for s in sig)
    if ai_n >= 3 and cam_n == 0:
        level = LEANS_AI
    elif cam_n >= 2 and ai_n == 0:
        level = CAMERA_LIKE
    elif ai_n or cam_n:
        level = MIXED
    else:
        level = UNCLEAR
    notes = ["These are rule-of-thumb pixel clues, not proof. Filters, compression and screenshots can fool them."]
    reliability = "low" if (heavy or min(w, h) < 400) else "medium"
    if reliability == "low":
        notes.append("Reliability is low: the picture is small or heavily compressed.")
    return PixelReport(config.STATUS_COMPLETED, level, sig, ai_n, cam_n, reliability, notes)