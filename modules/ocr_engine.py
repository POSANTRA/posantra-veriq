"""POSANTRA | VERIQ - OCR (Step 6).

Runs Tesseract with a fixed argument list (no shell) on a lightly
preprocessed temporary copy of the image. OCR output is evidence for
further investigation, not proof that the extracted text is accurate.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional

from PIL import Image, ImageOps

import config
from modules import security

MAX_TEXT_CHARS = 20_000
_MAX_SIDE = 3000          # downscale anything larger before OCR
_UPSCALE_BELOW = 1000     # upscale small images to help Tesseract
_LANG_PATTERN = re.compile(r"[A-Za-z_]{2,20}(\+[A-Za-z_]{2,20})*")


@dataclass
class OCRResult:
    status: str
    error: Optional[str] = None
    text: str = ""
    lines: list[str] = field(default_factory=list)
    word_count: int = 0
    mean_confidence: Optional[float] = None
    language: str = ""
    notes: list[str] = field(default_factory=list)


def _preprocess(data: bytes) -> bytes:
    """Return PNG bytes of a grayscale, contrast-stretched copy for OCR."""
    with Image.open(BytesIO(data)) as img:
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            img = Image.alpha_composite(background, rgba)
        gray = ImageOps.grayscale(img.convert("RGB"))

    longest = max(gray.size)
    if longest > _MAX_SIDE:
        scale = _MAX_SIDE / longest
        gray = gray.resize((max(1, int(gray.width * scale)), max(1, int(gray.height * scale))))
    elif longest < _UPSCALE_BELOW:
        scale = min(3.0, _UPSCALE_BELOW / longest)
        gray = gray.resize(
            (max(1, int(gray.width * scale)), max(1, int(gray.height * scale))),
            Image.LANCZOS,
        )
    gray = ImageOps.autocontrast(gray)

    buf = BytesIO()
    gray.save(buf, format="PNG")
    return buf.getvalue()


def _parse_tsv(tsv: str) -> tuple[list[str], list[float]]:
    """Group word rows (level 5) into lines; return (lines, word confidences)."""
    grouped: dict[tuple, list[str]] = {}
    confidences: list[float] = []
    for row in tsv.splitlines():
        parts = row.split("\t", 11)  # manual split: the text column may contain quotes
        if len(parts) < 12 or parts[0] != "5":
            continue
        word = parts[11].strip()
        if not word:
            continue
        try:
            conf = float(parts[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        grouped.setdefault((parts[2], parts[3], parts[4]), []).append(word)
        confidences.append(conf)
    return [" ".join(words) for words in grouped.values()], confidences


def extract_text(data: bytes, language: Optional[str] = None) -> OCRResult:
    """Run OCR. Never raises; reports Completed / Not available / Failed."""
    language = language or config.OCR_LANGUAGE
    if not _LANG_PATTERN.fullmatch(language):
        return OCRResult(status=config.STATUS_FAILED, error="Invalid OCR language setting.")

    exe = config.find_tool("tesseract")
    if not exe:
        return OCRResult(
            status=config.STATUS_NOT_AVAILABLE,
            error="Tesseract OCR is not installed or could not be found.",
            language=language,
        )

    try:
        prepared = _preprocess(data)
    except Exception as exc:
        return OCRResult(
            status=config.STATUS_FAILED,
            error=f"The image could not be prepared for OCR ({type(exc).__name__}).",
            language=language,
        )

    try:
        with security.secure_temp_file(prepared, ".png") as path:
            proc = subprocess.run(
                [exe, str(path), "stdout", "-l", language, "--psm", "3", "tsv"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=config.SUBPROCESS_TIMEOUT_SECONDS,
                shell=False,
            )
    except subprocess.TimeoutExpired:
        return OCRResult(status=config.STATUS_FAILED, error="OCR timed out.", language=language)
    except OSError as exc:
        return OCRResult(
            status=config.STATUS_FAILED,
            error=f"OCR could not be started ({type(exc).__name__}).",
            language=language,
        )

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        return OCRResult(
            status=config.STATUS_FAILED,
            error="Tesseract reported an error" + (f": {detail[0][:200]}" if detail else "."),
            language=language,
        )

    lines, confidences = _parse_tsv(proc.stdout)
    result = OCRResult(status=config.STATUS_COMPLETED, language=language)
    result.lines = lines
    result.text = "\n".join(lines)[:MAX_TEXT_CHARS]
    result.word_count = len(confidences)
    if confidences:
        result.mean_confidence = round(sum(confidences) / len(confidences), 1)

    if not lines:
        result.notes.append(
            "No text was detected. This does not mean the image contains no text; "
            "stylised, small, rotated or low-contrast text is often missed."
        )
    else:
        if result.mean_confidence is not None and result.mean_confidence < 60:
            result.notes.append(
                "Average OCR confidence is low, so the extracted text is likely to "
                "contain errors."
            )
        result.notes.append(
            "OCR output can contain misread characters. It is evidence for further "
            "investigation, not proof of what the image says. Language model used: "
            f"{language}."
        )
    return result