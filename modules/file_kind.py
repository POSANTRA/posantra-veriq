"""POSANTRA | VERIQ - file-kind detector (rule-based).

Reports what KIND of file this looks like (camera original, WhatsApp copy,
screenshot) from file facts only. Always 'looks like', never 'is'. It explains
why hidden labels may be missing; it says nothing about AI or real.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import config

CAMERA, WHATSAPP, SCREENSHOT, UNKNOWN = "camera", "whatsapp", "screenshot", "unknown"

_SHOT_NAME = re.compile(r"screen[\s_\-]?shot|screen[\s_\-]?(capture|recording)|^capture[\s_\-]?\d", re.I)
_WA_NAME = re.compile(r"^(whatsapp[\s_\-]?(image|video)|img-\d{8}-wa\d+)", re.I)

# Common phone and monitor screen sizes (width, height), matched in either orientation.
SCREEN_SIZES = {
    (750, 1334), (828, 1792), (1080, 1920), (1080, 2160), (1080, 2340), (1080, 2400),
    (1080, 2412), (1125, 2436), (1170, 2532), (1179, 2556), (1242, 2688), (1284, 2778),
    (1290, 2796), (1440, 3120), (1440, 3200), (1366, 768), (1536, 864), (1600, 900),
    (1920, 1080), (2560, 1440), (2880, 1800), (3840, 2160),
}


@dataclass
class FileKind:
    key: str
    icon: str
    label: str
    sentence: str
    evidence: list = field(default_factory=list)
    lost_info: bool = False


def _known_size(width: int, height: int) -> bool:
    return (width, height) in SCREEN_SIZES or (height, width) in SCREEN_SIZES


def detect(filename: str, info, meta) -> FileKind:
    name = filename or ""
    usable = meta is not None and getattr(meta, "status", None) == config.STATUS_COMPLETED
    found = (getattr(meta, "found", None) or {}) if usable else {}
    software = str(found.get("Software / creator tool", "")).lower()
    has_camera = bool(found.get("Camera make") or found.get("Camera model"))
    width, height = int(getattr(info, "width", 0) or 0), int(getattr(info, "height", 0) or 0)
    fmt = getattr(info, "format", "") or ""

    if has_camera:
        ev = ["Camera make or model is recorded in the file."]
        if fmt:
            ev.append(f"Format: {fmt}.")
        return FileKind(CAMERA, "📷", "Camera details found",
                        "The file carries camera details. They can be edited, so this is a clue, not proof.", ev)

    if _WA_NAME.search(name):
        ev = ["The file name follows WhatsApp's naming pattern."]
        if fmt == "JPEG":
            ev.append("JPEG with no camera details, which is what WhatsApp produces.")
        if max(width, height) and max(width, height) <= 1600:
            ev.append("Longest side is 1600 px or less, typical of WhatsApp compression.")
        return FileKind(WHATSAPP, "💬", "Looks like a WhatsApp copy",
                        "WhatsApp re-saves pictures and removes hidden labels and camera details.", ev, True)

    shot_ev = []
    if _SHOT_NAME.search(name):
        shot_ev.append("The file name says screenshot or screen capture.")
    if "screenshot" in software:
        shot_ev.append("The software field mentions a screenshot tool.")
    if width and height and _known_size(width, height):
        shot_ev.append(f"The size {width}x{height} px matches a common phone or screen size.")
        if fmt == "PNG":
            shot_ev.append("PNG with no camera details, which is how many screenshots are saved.")
    strong = any("name" in e or "software" in e for e in shot_ev) or len(shot_ev) >= 2
    if shot_ev and strong:
        return FileKind(SCREENSHOT, "🖥️", "Looks like a screenshot",
                        "Screenshots are new files that drop the original picture's hidden labels.",
                        shot_ev, True)

    return FileKind(UNKNOWN, "🗂️", "Source not clear",
                    "VERIQ cannot tell from the file facts how this picture was saved.", [])