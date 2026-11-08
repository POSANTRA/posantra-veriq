"""POSANTRA | VERIQ - place clues (presentation helper).

Reports only what the file itself embeds. Never infers the uploader's
location. Region lookup is optional, rounded, and user-triggered.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from modules import post_extractor as pe

OFFSET_TAGS = ("OffsetTimeOriginal", "OffsetTimeDigitized", "OffsetTime", "TimeZone")


def collect(meta) -> dict:
    """Return embedded GPS and time-zone offsets found in metadata (may be empty)."""
    out = {"gps": None, "offsets": []}
    if meta is None or getattr(meta, "status", None) != "Completed":
        return out
    gps = getattr(meta, "gps", None)
    if gps and gps.get("plausible", True) and not gps.get("warning"):
        out["gps"] = (float(gps["latitude"]), float(gps["longitude"]))
    seen = []
    for row in getattr(meta, "all_tags", None) or []:
        if row.get("Tag") in OFFSET_TAGS:
            value = str(row.get("Value", "")).strip()
            if value and value not in seen:
                seen.append(value)
    out["offsets"] = seen[:3]
    return out


def region_lookup(lat: float, lon: float) -> tuple[Optional[str], Optional[str]]:
    """Coarse region name via OpenStreetMap Nominatim. Coordinates rounded to 2 decimals."""
    url = "https://nominatim.openstreetmap.org/reverse?" + urlencode(
        {"format": "jsonv2", "lat": f"{lat:.2f}", "lon": f"{lon:.2f}", "zoom": 8,
         "accept-language": "en"})
    fetched = pe._safe_get(url, "application/json", 100_000)
    if not fetched.ok:
        return None, fetched.error
    if fetched.status_code != 200:
        return None, f"The lookup service answered HTTP {fetched.status_code}."
    try:
        import json
        data = json.loads(fetched.body.decode("utf-8", errors="replace"))
    except ValueError:
        return None, "The lookup service returned unreadable data."
    address = data.get("address") if isinstance(data, dict) else None
    if not isinstance(address, dict):
        return None, "No region was found for these coordinates."
    parts = [address.get(k) for k in ("state_district", "state", "country") if address.get(k)]
    return (", ".join(dict.fromkeys(parts)) or None), (None if parts else "No region was found.")