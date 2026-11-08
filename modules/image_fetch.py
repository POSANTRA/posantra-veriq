"""POSANTRA | VERIQ - safe download of a post's public preview picture.

Uses the same guarded fetcher as page retrieval (private addresses blocked,
every redirect re-checked, size and time limits). Never logs in or imitates a
browser session. The bytes are validated as a real image before use.
"""
from __future__ import annotations

from typing import Optional

import config
from modules import post_extractor as pe
from modules import security

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def fetch_post_image(urls: list) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    """Return (bytes, filename, error). Tries at most two public picture URLs."""
    problems: list[str] = []
    for url in list(urls or [])[:2]:
        fetched = pe._safe_get(
            url, "image/webp,image/png,image/jpeg,*/*;q=0.5", config.MAX_UPLOAD_BYTES)
        if not fetched.ok:
            problems.append(str(fetched.error))
            continue
        if fetched.status_code != 200:
            problems.append(f"The picture was refused (HTTP {fetched.status_code}).")
            continue
        if fetched.truncated:
            problems.append("The picture is larger than the size limit.")
            continue
        mime = security.detect_image_type(fetched.body)
        if mime not in _EXT:
            problems.append("The picture is not a supported image type (JPG, PNG, WebP).")
            continue
        return fetched.body, "post_preview" + _EXT[mime], None
    return None, None, " ".join(problems) or "The post offers no public picture."