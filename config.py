"""POSANTRA | VERIQ central configuration.

Single source of truth for branding, limits, paths and external-tool discovery.
Nothing here performs analysis. External tools are located, never assumed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------- Branding
ORG_NAME = "POSANTRA"
PRODUCT_NAME = "VERIQ"
PRODUCT_FULL_NAME = "POSANTRA | VERIQ"
PRODUCT_CATEGORY = "Digital Content Verification & Intelligence Platform"
PRODUCT_TAGLINE = "Detect. Investigate. Verify."
ORG_TAGLINE = "Understand. Investigate. Protect."

DISCLAIMER = (
    "VERIQ provides an evidence-based technical assessment using available "
    "information and analytical methods. It does not guarantee absolute "
    "authenticity, manipulation, authorship, origin, or intent. Results "
    "depend on the quality and availability of evidence."
)

# ------------------------------------------------------------------- Paths
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = BASE_DIR / "database" / "veriq.db"

# ------------------------------------------------------------ Upload limits
MAX_UPLOAD_MB = 10
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
# ------------------------------------------------------------ Image limits
MAX_IMAGE_PIXELS = 50_000_000     # reject images larger than this (decompression-bomb guard)
# ------------------------------------------------------------------- OCR
OCR_LANGUAGE = "eng"   # Tesseract language code(s), e.g. "eng" or "eng+hin" once installed
# ------------------------------------------------- Analysis component status
STATUS_COMPLETED = "Completed"
STATUS_NOT_AVAILABLE = "Not available"
STATUS_NOT_APPLICABLE = "Not applicable"
STATUS_FAILED = "Failed"
STATUS_MANUAL = "Requires manual investigation"

# ---------------------------------------------------------------- Timeouts
REQUEST_TIMEOUT_SECONDS = 10      # outbound HTTP (Phase 1, Mode B)
SUBPROCESS_TIMEOUT_SECONDS = 20   # ExifTool / Tesseract calls

# ------------------------------------------------------ External tool paths
# Override with environment variables if auto-detection fails:
#   VERIQ_EXIFTOOL_PATH, VERIQ_TESSERACT_PATH
_DEFAULT_LOCATIONS = {
    "tesseract": [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ],
    "exiftool": [
        r"C:\Tools\ExifTool\exiftool.exe",
        r"C:\Program Files\ExifTool\exiftool.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\ExifTool\exiftool.exe"),
    ],
}
_ENV_VARS = {
    "tesseract": "VERIQ_TESSERACT_PATH",
    "exiftool": "VERIQ_EXIFTOOL_PATH",
}


def find_tool(name: str) -> Optional[str]:
    """Return a verified executable path for 'tesseract' or 'exiftool', else None."""
    override = os.environ.get(_ENV_VARS[name])
    if override and Path(override).is_file():
        return override
    on_path = shutil.which(name)
    if on_path:
        return on_path
    for candidate in _DEFAULT_LOCATIONS[name]:
        if Path(candidate).is_file():
            return candidate
    return None


def _tool_version(path: str, args: list[str]) -> Optional[str]:
    """Run a tool with a fixed argument list (no shell) and return its first output line."""
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            shell=False,
        )
        output = (result.stdout or result.stderr).strip()
        return output.splitlines()[0] if output else None
    except (OSError, subprocess.SubprocessError):
        return None


def tool_status() -> dict[str, dict]:
    """Honest availability report for external tools."""
    status: dict[str, dict] = {}
    for name, args in (("tesseract", ["--version"]), ("exiftool", ["-ver"])):
        path = find_tool(name)
        version = _tool_version(path, args) if path else None
        status[name] = {
            "available": bool(path and version),
            "path": path,
            "version": version,
        }
    return status
# ------------------------------------------------ experimental AI-pixel check
AI_MODEL_ID = "umm-maybe/AI-image-detector"   # Hugging Face model; change if it disappoints
AI_MODEL_IDS = ["umm-maybe/AI-image-detector", "Organika/sdxl-detector"]   # ensemble; verify names on huggingface.co

if __name__ == "__main__":
    print(PRODUCT_FULL_NAME, "-", PRODUCT_TAGLINE)
    for tool, info in tool_status().items():
        print(f"{tool}: {info}")