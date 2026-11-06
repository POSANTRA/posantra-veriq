"""POSANTRA | VERIQ - upload security helpers.

All uploaded content is untrusted. Nothing here executes uploaded data;
it only inspects bytes and manages temporary files safely.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import config

# Which extensions are legitimate for each detected content type.
_MIME_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    safe_name: str = "upload"
    extension: str = ""
    detected_mime: Optional[str] = None
    size_bytes: int = 0
    sha256: str = ""


def sanitize_filename(name: str) -> str:
    """Return a filename that is safe to display and store.

    Strips directory components (both / and \\), replaces unsafe characters,
    removes leading dots and limits length. Never returns an empty string.
    """
    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    name = _SAFE_CHARS.sub("_", name).lstrip(".")
    stem, ext = os.path.splitext(name)
    ext = ext[:10]
    stem = stem[: 100 - len(ext)]
    name = f"{stem}{ext}"
    return name or "upload"


def detect_image_type(data: bytes) -> Optional[str]:
    """Identify the real content type from magic bytes, ignoring the filename."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_upload(filename: str, data: bytes) -> ValidationResult:
    """Validate an upload. Collects every problem rather than stopping at the first."""
    result = ValidationResult(ok=False)
    result.safe_name = sanitize_filename(filename)
    result.extension = os.path.splitext(result.safe_name)[1].lower()
    result.size_bytes = len(data)

    if result.size_bytes == 0:
        result.errors.append("The file is empty.")
        return result

    if result.size_bytes > config.MAX_UPLOAD_BYTES:
        result.errors.append(
            f"The file is {result.size_bytes / (1024 * 1024):.1f} MB, which exceeds "
            f"the {config.MAX_UPLOAD_MB} MB limit."
        )
        return result

    result.sha256 = hashlib.sha256(data).hexdigest()

    if result.extension not in config.ALLOWED_EXTENSIONS:
        result.errors.append(
            "Unsupported file extension. Allowed: "
            + ", ".join(sorted(config.ALLOWED_EXTENSIONS))
            + "."
        )

    detected = detect_image_type(data)
    result.detected_mime = detected
    if detected is None or detected not in config.ALLOWED_MIME_TYPES:
        result.errors.append(
            "The file content is not a supported image (JPEG, PNG or WebP). "
            "The file extension alone is not trusted."
        )
    elif (
        result.extension in config.ALLOWED_EXTENSIONS
        and result.extension not in _MIME_EXTENSIONS[detected]
    ):
        result.errors.append(
            f"The extension '{result.extension}' does not match the actual file "
            f"content ({detected})."
        )

    result.ok = not result.errors
    return result


@contextmanager
def secure_temp_file(data: bytes, suffix: str = "") -> Iterator[Path]:
    """Write data to a temp file with a random name; always delete it afterwards.

    The user's filename is never used for the path. Pass only a validated
    extension as suffix.
    """
    if suffix and not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
        suffix = ""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="veriq_", suffix=suffix, dir=config.UPLOAD_DIR)
    path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        yield path
    finally:
        try:
            path.unlink()
        except OSError:
            pass