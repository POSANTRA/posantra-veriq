"""POSANTRA | VERIQ - basic image analysis (Step 4).

Confirms the image genuinely decodes and reports basic properties.
This is not forensic analysis; it only describes the file.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from PIL import Image, ImageStat

import config

# Backstop. The explicit pixel check below is the primary guard.
Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS


@dataclass
class ImageInfo:
    status: str
    error: Optional[str] = None
    format: Optional[str] = None
    mime: Optional[str] = None
    width: int = 0
    height: int = 0
    megapixels: float = 0.0
    mode: Optional[str] = None
    channels: int = 0
    has_alpha: bool = False
    animated: bool = False
    frames: int = 1
    mean_rgb: Optional[tuple[int, int, int]] = None


_FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def _failed(message: str) -> ImageInfo:
    return ImageInfo(status=config.STATUS_FAILED, error=message)


def analyze_basic(data: bytes, expected_mime: Optional[str] = None) -> ImageInfo:
    """Decode the image fully and return basic properties. Never raises."""
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = img.format
            mime = _FORMAT_TO_MIME.get(fmt or "")
            width, height = img.size

            if mime is None:
                return _failed(f"Unsupported image format reported by decoder: {fmt}.")
            if expected_mime and mime != expected_mime:
                return _failed(
                    f"Decoder format ({mime}) does not match the detected "
                    f"content type ({expected_mime})."
                )
            if width <= 0 or height <= 0:
                return _failed("The image has invalid dimensions.")
            if width * height > config.MAX_IMAGE_PIXELS:
                return _failed(
                    f"The image is {width}x{height} pixels, which exceeds the "
                    f"safety limit of {config.MAX_IMAGE_PIXELS:,} pixels."
                )

            img.load()  # full decode; raises on truncated or corrupted data

            bands = img.getbands()
            frames = getattr(img, "n_frames", 1)

            mean_rgb = None
            try:
                preview = img.convert("RGB")
                preview.thumbnail((256, 256))
                mean_rgb = tuple(int(round(v)) for v in ImageStat.Stat(preview).mean[:3])
            except Exception:
                mean_rgb = None

            return ImageInfo(
                status=config.STATUS_COMPLETED,
                format=fmt,
                mime=mime,
                width=width,
                height=height,
                megapixels=round(width * height / 1_000_000, 2),
                mode=img.mode,
                channels=len(bands),
                has_alpha=("A" in bands) or ("transparency" in img.info),
                animated=frames > 1,
                frames=frames,
                mean_rgb=mean_rgb,
            )
    except Image.DecompressionBombError:
        return _failed("The image is too large to process safely.")
    except Image.UnidentifiedImageError:
        return _failed("The file could not be recognised as a valid image.")
    except (OSError, ValueError, SyntaxError) as exc:
        return _failed(f"The image appears corrupted or truncated ({type(exc).__name__}).")
    except Exception as exc:  # never crash the app on hostile input
        return _failed(f"Unexpected error while reading the image ({type(exc).__name__}).")