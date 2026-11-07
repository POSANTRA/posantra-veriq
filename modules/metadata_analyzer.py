"""POSANTRA | VERIQ - metadata analysis (Step 5).

Reads embedded metadata with ExifTool (fixed arguments, no shell) and falls
back to a limited Pillow EXIF reader. Metadata is treated as a lead, never
as proof: it can be edited, stripped or fabricated, and its absence is normal.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

from PIL import ExifTags, Image

import config
from modules import security

# ExifTool groups that describe the temporary file we created, not the upload.
_IGNORED_GROUPS = {"System", "File", "ExifTool"}

MAX_TAGS_SHOWN = 500
_VALUE_LIMIT = 300

SOFTWARE_LABEL = "Software / creator tool"

# (display label, tag names in priority order). Names follow ExifTool naming;
# Pillow's differing names (DateTime, DateTimeDigitized) are included too.
_KEY_FIELDS: list[tuple[str, list[str]]] = [
    ("Camera make", ["Make"]),
    ("Camera model", ["Model"]),
    ("Lens", ["LensModel", "LensID"]),
    (SOFTWARE_LABEL, ["Software", "CreatorTool", "HistorySoftwareAgent"]),
    ("Date/time original", ["DateTimeOriginal"]),
    ("Date/time created", ["CreateDate", "DateTimeDigitized"]),
    ("Date/time modified", ["ModifyDate", "DateTime"]),
    ("Orientation", ["Orientation"]),
    ("Author / artist", ["Artist", "Creator", "Author"]),
    ("Copyright", ["Copyright", "Rights"]),
]

_ORIENTATION = {
    1: "Normal (1)",
    2: "Mirrored horizontally (2)",
    3: "Rotated 180 degrees (3)",
    4: "Mirrored vertically (4)",
    5: "Mirrored, rotated 90 degrees CCW (5)",
    6: "Rotated 90 degrees CW (6)",
    7: "Mirrored, rotated 90 degrees CW (7)",
    8: "Rotated 90 degrees CCW (8)",
}

# Software names associated with editing or image generation. A match is
# reported as an observation only.
_NOTABLE_SOFTWARE = [
    "photoshop", "lightroom", "gimp", "affinity", "canva", "snapseed",
    "picsart", "pixelmator", "paint.net", "capture one", "luminar",
    "stable diffusion", "midjourney", "dall-e", "firefly", "comfyui",
    "automatic1111",
]


class _ExifToolError(Exception):
    """ExifTool was unavailable or produced unusable output."""


@dataclass(frozen=True)
class Tag:
    group: str
    name: str
    value: Any


@dataclass
class MetadataResult:
    status: str
    source: Optional[str] = None
    error: Optional[str] = None
    found: dict[str, str] = field(default_factory=dict)
    absent: list[str] = field(default_factory=list)
    gps: Optional[dict] = None
    all_tags: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def _display(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).replace("\x00", "").strip()
    return text if len(text) <= _VALUE_LIMIT else text[:_VALUE_LIMIT] + "…"


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _orientation_text(value: Any) -> str:
    number = _to_float(value)
    if number is not None and int(number) == number and int(number) in _ORIENTATION:
        return _ORIENTATION[int(number)]
    return _display(value)


def _visible(tags: list[Tag]) -> list[Tag]:
    return [t for t in tags if t.group not in _IGNORED_GROUPS]


def _lookup(visible: list[Tag], names: list[str], groups: Optional[set] = None) -> Any:
    for name in names:
        for tag in visible:
            if tag.name != name:
                continue
            if groups is not None and tag.group not in groups:
                continue
            if tag.value is None or _display(tag.value) == "":
                continue
            return tag.value
    return None


# ------------------------------------------------------------------ ExifTool
def _run_exiftool(file_path) -> dict:
    """Run ExifTool on one file with a fixed argument list (no shell)."""
    exe = config.find_tool("exiftool")
    if not exe:
        raise _ExifToolError("ExifTool is not installed or could not be found.")
    try:
        proc = subprocess.run(
            [exe, "-json", "-G1", "-a", "-n", str(file_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.SUBPROCESS_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise _ExifToolError("ExifTool timed out.")
    except OSError as exc:
        raise _ExifToolError(f"ExifTool could not be started ({type(exc).__name__}).")

    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        raise _ExifToolError("ExifTool returned output that could not be read.")
    if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], dict):
        raise _ExifToolError("ExifTool returned no usable data.")
    return parsed[0]


def _tags_from_exiftool(raw: dict) -> list[Tag]:
    tags: list[Tag] = []
    for key, value in raw.items():
        if ":" not in key:
            continue  # e.g. SourceFile
        group, name = key.split(":", 1)
        tags.append(Tag(group, name, value))
    return tags


# -------------------------------------------------------------------- Pillow
def _dms_to_float(value: Any) -> Optional[float]:
    try:
        degrees, minutes, seconds = (float(v) for v in value)
        return degrees + minutes / 60.0 + seconds / 3600.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _tags_from_pillow(data: bytes) -> list[Tag]:
    """Limited fallback: EXIF (IFD0, Exif, GPS) and PNG text chunks only."""
    tags: list[Tag] = []
    with Image.open(BytesIO(data)) as img:
        exif = img.getexif()
        for tag_id, value in exif.items():
            if tag_id in (0x8769, 0x8825):  # pointers to sub-IFDs
                continue
            name = ExifTags.TAGS.get(tag_id, f"Tag0x{tag_id:04X}")
            tags.append(Tag("IFD0", name, _display(value) if not isinstance(value, (int, float)) else value))

        try:
            for tag_id, value in exif.get_ifd(0x8769).items():
                name = ExifTags.TAGS.get(tag_id, f"Tag0x{tag_id:04X}")
                tags.append(Tag("ExifIFD", name, _display(value) if not isinstance(value, (int, float)) else value))
        except Exception:
            pass

        try:
            for tag_id, value in exif.get_ifd(0x8825).items():
                name = ExifTags.GPSTAGS.get(tag_id, f"GPSTag0x{tag_id:04X}")
                if name in ("GPSLatitude", "GPSLongitude"):
                    value = _dms_to_float(value)
                    if value is None:
                        continue
                elif not isinstance(value, (int, float)):
                    value = _display(value)
                tags.append(Tag("GPS", name, value))
        except Exception:
            pass

        if img.format == "PNG":
            for key, value in img.info.items():
                if isinstance(key, str) and isinstance(value, str):
                    tags.append(Tag("PNG", key, _display(value)))
    return tags


# --------------------------------------------------------------------- GPS

def _extract_gps(visible: list[Tag]) -> Optional[dict]:
    coords: dict[str, float] = {}
    for axis, negative_ref in (("Latitude", "S"), ("Longitude", "W")):
        # Composite tags are already signed; raw GPS tags need the N/S/E/W ref.
        value = _to_float(_lookup(visible, [f"GPS{axis}"], {"Composite"}))
        if value is None:
            raw = _to_float(_lookup(visible, [f"GPS{axis}"]))
            if raw is not None:
                ref = _display(_lookup(visible, [f"GPS{axis}Ref"]) or "").upper()
                value = -abs(raw) if ref == negative_ref else raw
        if value is None:
            return None
        coords[axis.lower()] = value

    lat, lon = coords["latitude"], coords["longitude"]
    plausible = -90 <= lat <= 90 and -180 <= lon <= 180
    warning = None
    if not plausible:
        warning = "These values are outside valid coordinate ranges and are unreliable."
    elif lat == 0 and lon == 0:
        warning = "0, 0 is a common placeholder value and is unlikely to be a real location."
    return {"latitude": lat, "longitude": lon, "plausible": plausible, "warning": warning}
# ------------------------------------------------- Content Credentials (C2PA)
@dataclass
class MetadataResult:
    status: str
    source: Optional[str] = None
    error: Optional[str] = None
    found: dict[str, str] = field(default_factory=dict)
    absent: list[str] = field(default_factory=list)
    gps: Optional[dict] = None
    content_credentials: Optional[dict] = None
    all_tags: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
_DIGITAL_SOURCE_LABELS = {
    "trainedAlgorithmicMedia": "AI-generated (trained algorithmic media)",
    "compositeWithTrainedAlgorithmicMedia": "Composite that includes AI-generated elements",
    "algorithmicMedia": "Algorithmically generated media",
    "digitalCapture": "Digital capture",
    "computationalCapture": "Computational capture",
    "digitalCreation": "Digital creation",
    "compositeCapture": "Composite of captured content",
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_display(v) for v in value]
    return [_display(value)]


def _extract_content_credentials(visible: list[Tag]) -> Optional[dict]:
    """Summarise an embedded C2PA manifest, if ExifTool exposed one.

    This reports what the manifest CLAIMS. The signature is not validated.
    """
    is_c2pa = any(
        t.group == "JUMBF" and t.name == "JUMDLabel" and _display(t.value).lower() == "c2pa"
        for t in visible
    )
    cbor = [t for t in visible if t.group == "CBOR"]
    if not is_c2pa and not cbor:
        return None

    sources: list[str] = []
    for raw in _as_list(_lookup(cbor, ["ActionsDigitalSourceType"])):
        key = raw.rstrip("/").rsplit("/", 1)[-1]
        sources.append(_DIGITAL_SOURCE_LABELS.get(key, key))

    agent_name = _lookup(cbor, ["ActionsSoftwareAgentName"])
    agent_version = _lookup(cbor, ["ActionsSoftwareAgentVersion"])
    agent = " ".join(
        _display(v) for v in (agent_name, agent_version) if v is not None
    ) or None

    generator = _lookup(cbor, ["Claim_Generator_InfoName"])
    return {
        "generator": _display(generator) if generator is not None else None,
        "software_agent": agent,
        "digital_source_types": list(dict.fromkeys(sources)),
        "actions": list(dict.fromkeys(_as_list(_lookup(cbor, ["ActionsAction"])))),
        "when": list(dict.fromkeys(_as_list(_lookup(cbor, ["ActionsWhen"])))),
    }


# ------------------------------------------------------------------ assemble
# ------------------------------------------------- Content Credentials (C2PA)
_DIGITAL_SOURCE_LABELS = {
    "trainedAlgorithmicMedia": "AI-generated (trained algorithmic media)",
    "compositeWithTrainedAlgorithmicMedia": "Composite that includes AI-generated elements",
    "algorithmicMedia": "Algorithmically generated media",
    "digitalCapture": "Digital capture",
    "computationalCapture": "Computational capture",
    "digitalCreation": "Digital creation",
    "compositeCapture": "Composite of captured content",
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_display(v) for v in value]
    return [_display(value)]


def _extract_content_credentials(visible: list[Tag]) -> Optional[dict]:
    """Summarise an embedded C2PA manifest, if ExifTool exposed one.

    This reports what the manifest CLAIMS. The signature is not validated.
    """
    is_c2pa = any(
        t.group == "JUMBF" and t.name == "JUMDLabel" and _display(t.value).lower() == "c2pa"
        for t in visible
    )
    cbor = [t for t in visible if t.group == "CBOR"]
    if not is_c2pa and not cbor:
        return None

    sources: list[str] = []
    for raw in _as_list(_lookup(cbor, ["ActionsDigitalSourceType"])):
        key = raw.rstrip("/").rsplit("/", 1)[-1]
        sources.append(_DIGITAL_SOURCE_LABELS.get(key, key))

    agent_name = _lookup(cbor, ["ActionsSoftwareAgentName"])
    agent_version = _lookup(cbor, ["ActionsSoftwareAgentVersion"])
    agent = " ".join(
        _display(v) for v in (agent_name, agent_version) if v is not None
    ) or None

    generator = _lookup(cbor, ["Claim_Generator_InfoName"])
    return {
        "generator": _display(generator) if generator is not None else None,
        "software_agent": agent,
        "digital_source_types": list(dict.fromkeys(sources)),
        "actions": list(dict.fromkeys(_as_list(_lookup(cbor, ["ActionsAction"])))),
        "when": list(dict.fromkeys(_as_list(_lookup(cbor, ["ActionsWhen"])))),
    }
def _build_result(tags: list[Tag], source: str) -> MetadataResult:
    visible = _visible(tags)
    result = MetadataResult(status=config.STATUS_COMPLETED, source=source)

    for label, names in _KEY_FIELDS:
        value = _lookup(visible, names)
        if value is None:
            result.absent.append(label)
        elif label == "Orientation":
            result.found[label] = _orientation_text(value)
        else:
            result.found[label] = _display(value)

    result.gps = _extract_gps(visible)
    if result.gps is None:
        result.absent.append("GPS location")
        result.content_credentials = _extract_content_credentials(visible)
    if result.content_credentials:
        result.notes.append(
            "This file contains Content Credentials (C2PA) metadata. VERIQ reads what "
            "the manifest claims but has not validated its signature. Many genuine and "
            "AI-generated files carry no such metadata, so its absence in other files "
            "means nothing."
        )

    rows = sorted(
        ({"Group": t.group, "Tag": t.name, "Value": _display(t.value)} for t in visible),
        key=lambda r: (r["Group"], r["Tag"]),
    )
    if len(rows) > MAX_TAGS_SHOWN:
        result.notes.append(
            f"Only the first {MAX_TAGS_SHOWN} of {len(rows)} embedded tags are listed."
        )
        rows = rows[:MAX_TAGS_SHOWN]
    result.all_tags = rows

    software = result.found.get(SOFTWARE_LABEL, "")
    hits = [name for name in _NOTABLE_SOFTWARE if name in software.lower()]
    if hits:
        result.notes.append(
            f"The software field names '{software}', which is associated with image "
            "editing or generation. This shows the file passed through that software "
            "at some point. It does not show that the content was manipulated."
        )

    if not result.found and not result.all_tags:
        result.notes.append(
            "No embedded metadata was found. This is common for screenshots, "
            "messaging-app and social-media downloads and exported images, and is "
            "not evidence of manipulation."
        )
    result.notes.append(
        "Embedded metadata can be edited, stripped or fabricated. Treat it as a lead "
        "for further investigation, not as proof."
    )
    return result


def analyze_metadata(data: bytes, extension: str = "", use_exiftool: bool = True) -> MetadataResult:
    """Extract metadata. Never raises; reports which tool actually ran."""
    pre_notes: list[str] = []
    tags: Optional[list[Tag]] = None
    source: Optional[str] = None

    if use_exiftool:
        try:
            with security.secure_temp_file(data, extension) as path:
                raw = _run_exiftool(path)
            tags = _tags_from_exiftool(raw)
            source = "ExifTool"
        except _ExifToolError as exc:
            pre_notes.append(
                f"ExifTool was not used: {exc} A limited built-in EXIF reader was used "
                "instead, so some metadata (such as XMP) may be missing from this report."
            )
        except OSError as exc:
            pre_notes.append(
                f"ExifTool could not be run because a temporary file could not be "
                f"created ({type(exc).__name__}). A limited built-in EXIF reader was used instead."
            )

    if tags is None:
        try:
            tags = _tags_from_pillow(data)
            source = "Pillow EXIF reader (limited)"
        except Exception as exc:
            return MetadataResult(
                status=config.STATUS_FAILED,
                error=f"Metadata could not be read ({type(exc).__name__}).",
                notes=pre_notes,
            )

    result = _build_result(tags, source or "Unknown")
    result.notes = pre_notes + result.notes
    return result