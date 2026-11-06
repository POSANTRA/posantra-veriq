"""POSANTRA | VERIQ - basic forensic indicators (Step 7).

Lightweight, local indicators about how an image file was encoded.
These are INDICATORS, not proof of manipulation: legitimate editing,
resizing and platform recompression change them, and their absence
does not demonstrate authenticity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional

import numpy as np
from PIL import Image, ImageChops, JpegImagePlugin

import config

ELA_QUALITY = 90
ELA_MAX_PIXELS = 12_000_000      # skip ELA above this to keep memory use modest
_ELA_DISPLAY_SIDE = 1000
_GRID = 8
_SUBSAMPLING = {0: "4:4:4 (none)", 1: "4:2:2", 2: "4:2:0"}

# Chunk names used by some AI image tools. Names only; values are not interpreted.
_GENERATOR_KEYS = {
    "parameters", "prompt", "workflow", "sd-metadata",
    "invokeai_metadata", "invokeai_graph", "dream",
}

# Standard JPEG luminance quantization table (natural order).
_STD_LUMA = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]
_ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
]
_STD_LUMA_ZZ = [_STD_LUMA[i] for i in _ZIGZAG]

NAME_QUANT = "JPEG quantization tables"
NAME_SUBSAMPLING = "Chroma subsampling"
NAME_ENCODING = "Encoding mode"
NAME_JPEG_NA = "JPEG compression analysis"
NAME_ELA = "Error level analysis (ELA)"
NAME_CHUNKS = "Generator text chunks"

LIMITATIONS = [
    "These are forensic indicators, not proof of manipulation. Cropping, resizing, "
    "screenshots and social-media recompression all change them in ordinary files.",
    "The absence of indicators does not show that an image is authentic. "
    "Careful edits and AI-generated images often leave none of these signals.",
    "Heavily compressed or repeatedly re-saved images make every indicator less reliable.",
]


@dataclass
class Indicator:
    name: str
    status: str
    summary: str
    detail: str = ""
    significance: str = "info"   # "info" or "observation" (worth a closer human look)


@dataclass
class ForensicResult:
    status: str
    error: Optional[str] = None
    indicators: list[Indicator] = field(default_factory=list)
    ela_png: Optional[bytes] = None
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))


# ------------------------------------------------------------- quantization
def _scaled_table(base: list[int], quality: int) -> list[int]:
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality
    return [min(255, max(1, (v * scale + 50) // 100)) for v in base]


def estimate_quality(table: list[int]) -> Optional[tuple[int, float]]:
    """Return (nearest standard libjpeg quality, mean absolute deviation)."""
    if len(table) != 64:
        return None
    best: Optional[tuple[int, float]] = None
    for base in (_STD_LUMA, _STD_LUMA_ZZ):   # tolerate either coefficient order
        for quality in range(1, 101):
            cand = _scaled_table(base, quality)
            err = sum(abs(a - b) for a, b in zip(table, cand)) / 64.0
            if best is None or err < best[1]:
                best = (quality, err)
    return best


def _quant_indicator(img: Image.Image) -> Indicator:
    tables = getattr(img, "quantization", None)
    if not tables or 0 not in tables:
        return Indicator(NAME_QUANT, config.STATUS_NOT_AVAILABLE,
                         "No quantization tables could be read from this file.")
    estimate = estimate_quality([int(v) for v in tables[0]])
    if estimate is None:
        return Indicator(NAME_QUANT, config.STATUS_NOT_AVAILABLE,
                         "The quantization table has an unexpected shape.")
    quality, err = estimate
    if err <= 1.0:
        summary = (f"Consistent with standard JPEG tables at an estimated quality "
                   f"of about {quality}.")
        detail = "Many encoders produce these tables, so this identifies no particular software."
        if quality <= 50:
            detail += (" This is heavy compression, which reduces the reliability "
                       "of the other indicators.")
    else:
        summary = (f"Non-standard (custom) quantization tables; nearest standard "
                   f"quality is about {quality} (mean deviation {err:.1f}).")
        detail = ("Cameras, phones, editors and some platforms use custom tables. "
                  "This alone says nothing about manipulation.")
    return Indicator(NAME_QUANT, config.STATUS_COMPLETED, summary, detail)


def _subsampling_indicator(img: Image.Image) -> Indicator:
    try:
        code = JpegImagePlugin.get_sampling(img)
    except Exception:
        code = -1
    if code not in _SUBSAMPLING:
        return Indicator(NAME_SUBSAMPLING, config.STATUS_NOT_AVAILABLE,
                         "Chroma subsampling could not be determined.")
    return Indicator(NAME_SUBSAMPLING, config.STATUS_COMPLETED, _SUBSAMPLING[code],
                     "A format characteristic. Different encoders default to different modes.")


def _encoding_indicator(img: Image.Image) -> Indicator:
    progressive = bool(img.info.get("progressive") or img.info.get("progression"))
    icc = "icc_profile" in img.info
    summary = ("Progressive" if progressive else "Baseline") + (
        ", ICC colour profile embedded" if icc else ", no ICC colour profile")
    return Indicator(NAME_ENCODING, config.STATUS_COMPLETED, summary,
                     "A format characteristic, not evidence of editing.")


# --------------------------------------------------------------------- ELA
def _ela_indicator(data: bytes, fmt: Optional[str]) -> tuple[Indicator, Optional[bytes]]:
    if fmt != "JPEG":
        return Indicator(
            NAME_ELA, config.STATUS_NOT_APPLICABLE,
            "ELA is designed for JPEG files and is not meaningful for this format.",
            "PNG is lossless and WebP may be lossy or lossless, so re-saving as JPEG "
            "would not reveal compression history the way it can for a JPEG.",
        ), None

    with Image.open(BytesIO(data)) as img:
        if img.width * img.height > ELA_MAX_PIXELS:
            return Indicator(
                NAME_ELA, config.STATUS_NOT_AVAILABLE,
                f"Skipped: image exceeds the {ELA_MAX_PIXELS:,}-pixel limit for ELA.",
            ), None
        original = img.convert("RGB")

    buf = BytesIO()
    original.save(buf, format="JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    with Image.open(buf) as resaved_img:
        resaved = resaved_img.convert("RGB")

    diff = np.asarray(ImageChops.difference(original, resaved), dtype=np.float32).mean(axis=2)
    mean_val = float(diff.mean())
    p99 = float(np.percentile(diff, 99))
    max_val = float(diff.max())

    ratio: Optional[float] = None
    h, w = diff.shape
    gh, gw = h // _GRID, w // _GRID
    if gh >= 1 and gw >= 1:
        cells = diff[: gh * _GRID, : gw * _GRID].reshape(_GRID, gh, _GRID, gw).mean(axis=(1, 3))
        ratio = float(cells.max() / (np.median(cells) + 0.01))

    scale = 255.0 / max(max_val, 1.0)
    heat = Image.fromarray(np.clip(diff * scale, 0, 255).astype("uint8"), mode="L")
    heat.thumbnail((_ELA_DISPLAY_SIDE, _ELA_DISPLAY_SIDE))
    out = BytesIO()
    heat.save(out, format="PNG")

    summary = (f"Mean difference {mean_val:.2f}, 99th percentile {p99:.1f}, "
               f"maximum {max_val:.0f} (re-saved at quality {ELA_QUALITY}).")
    significance = "info"
    detail = ("Review the heatmap below. Edges, text and fine texture respond more "
              "strongly in ordinary photos, so a bright area is not by itself a sign of editing.")
    if ratio is not None:
        summary += f" Strongest region is {ratio:.1f}x the median region."
        if ratio >= 5:
            significance = "observation"
            detail = ("Some regions respond noticeably more strongly than others. "
                      "Sharp edges, text and saturated detail do this naturally, so "
                      "treat it as a prompt for human review, not as a finding of editing.")
    return Indicator(NAME_ELA, config.STATUS_COMPLETED, summary, detail, significance), out.getvalue()


# ------------------------------------------------------------ PNG text chunks
def _chunks_indicator(img: Image.Image) -> Indicator:
    if img.format != "PNG":
        return Indicator(NAME_CHUNKS, config.STATUS_NOT_APPLICABLE,
                         "Only checked for PNG files.")
    found = sorted(k for k in img.info if isinstance(k, str) and k.lower() in _GENERATOR_KEYS)
    if found:
        return Indicator(
            NAME_CHUNKS, config.STATUS_COMPLETED,
            "Found text chunks named: " + ", ".join(found) + ".",
            "These names are used by some AI image tools to store generation settings. "
            "Only the names are reported; the values are not interpreted. Anyone can add "
            "or remove such chunks.",
            "observation",
        )
    return Indicator(
        NAME_CHUNKS, config.STATUS_COMPLETED,
        "No chunk names associated with common AI image tools were found.",
        "Most AI-generated images carry no such chunks, so this says nothing either way.",
    )


# ------------------------------------------------------------------- entry
def analyze_forensics(data: bytes) -> ForensicResult:
    """Run all indicators. Never raises; each indicator reports its own status."""
    result = ForensicResult(status=config.STATUS_COMPLETED)
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = img.format
            if fmt == "JPEG":
                steps = [_quant_indicator, _subsampling_indicator, _encoding_indicator]
                for step in steps:
                    try:
                        result.indicators.append(step(img))
                    except Exception as exc:
                        result.indicators.append(Indicator(
                            step.__name__.strip("_"), config.STATUS_FAILED,
                            f"Could not be computed ({type(exc).__name__})."))
            else:
                result.indicators.append(Indicator(
                    NAME_JPEG_NA, config.STATUS_NOT_APPLICABLE,
                    "Quantization, subsampling and encoding-mode checks apply to JPEG files only."))
            try:
                result.indicators.append(_chunks_indicator(img))
            except Exception as exc:
                result.indicators.append(Indicator(
                    NAME_CHUNKS, config.STATUS_FAILED,
                    f"Could not be computed ({type(exc).__name__})."))
    except Exception as exc:
        return ForensicResult(
            status=config.STATUS_FAILED,
            error=f"The image could not be opened for forensic analysis ({type(exc).__name__}).",
        )

    try:
        indicator, png = _ela_indicator(data, fmt)
        result.indicators.append(indicator)
        result.ela_png = png
    except Exception as exc:
        result.indicators.append(Indicator(
            NAME_ELA, config.STATUS_FAILED, f"Could not be computed ({type(exc).__name__})."))
    return result