"""POSANTRA | VERIQ - image fingerprinting.

SHA-256 identifies a byte-identical file. Perceptual hashes (aHash, pHash,
dHash) stay similar when an image is resized or recompressed. Similarity is
an indicator of visual resemblance, not proof of shared origin: flips,
crops and heavy edits can defeat these hashes, and unrelated simple images
can collide.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional

import imagehash
from PIL import Image, ImageStat

import config

HASH_SIZE = 8                  # 8x8 = 64-bit hashes (16 hex characters)
NEAR_IDENTICAL_MAX = 4         # rule-of-thumb thresholds, not validated cutoffs
SIMILAR_MAX = 10
LOW_DETAIL_STDDEV = 3.0
MAX_MATCHES = 10

LEVEL_NEAR = "Near-identical"
LEVEL_SIMILAR = "Visually similar"


@dataclass
class HashResult:
    status: str
    error: Optional[str] = None
    sha256: str = ""
    ahash: str = ""
    phash: str = ""
    dhash: str = ""
    low_detail: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Match:
    sha256: str
    filename: str
    first_seen: str
    times_seen: int
    ahash_distance: int
    phash_distance: int
    dhash_distance: int
    level: str
    origin: str = ""           # what the earlier file said about itself: ai / camera / credentials / ""


def hamming_distance(a: str, b: str) -> Optional[int]:
    """Number of differing bits between two equal-length hex hashes, else None."""
    if not a or not b or len(a) != len(b):
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return img.convert("RGB")


def compute_hashes(data: bytes) -> HashResult:
    """Compute SHA-256 and perceptual hashes. Never raises."""
    sha = hashlib.sha256(data).hexdigest()
    try:
        with Image.open(BytesIO(data)) as img:
            img.load()
            rgb = _flatten_to_rgb(img)
        result = HashResult(
            status=config.STATUS_COMPLETED,
            sha256=sha,
            ahash=str(imagehash.average_hash(rgb, hash_size=HASH_SIZE)),
            phash=str(imagehash.phash(rgb, hash_size=HASH_SIZE)),
            dhash=str(imagehash.dhash(rgb, hash_size=HASH_SIZE)),
        )
        gray = rgb.convert("L")
        gray.thumbnail((128, 128))
        if ImageStat.Stat(gray).stddev[0] < LOW_DETAIL_STDDEV:
            result.low_detail = True
            result.notes.append(
                "This image has very little visual detail (nearly uniform). "
                "Perceptual hashes of such images are unreliable and can match "
                "unrelated images."
            )
        result.notes.append(
            "Perceptual hashes tolerate resizing and recompression but can be "
            "defeated by cropping, flipping, rotation or heavy edits."
        )
        return result
    except Exception as exc:
        return HashResult(
            status=config.STATUS_FAILED,
            sha256=sha,
            error=f"Perceptual hashes could not be computed ({type(exc).__name__}).",
        )


def classify(ahash_d: int, phash_d: int, dhash_d: int) -> Optional[str]:
    """Return a similarity level using the stricter of pHash and dHash, else None."""
    worst = max(phash_d, dhash_d)
    if worst <= NEAR_IDENTICAL_MAX:
        return LEVEL_NEAR
    if worst <= SIMILAR_MAX:
        return LEVEL_SIMILAR
    return None


def compare_to_records(hashes: HashResult, records: list[dict]) -> list[Match]:
    """Compare against stored fingerprints. Byte-identical files are excluded
    here (they are reported separately as exact matches)."""
    if hashes.status != config.STATUS_COMPLETED or hashes.low_detail:
        return []
    matches: list[Match] = []
    for rec in records:
        if rec.get("sha256") == hashes.sha256:
            continue
        a = hamming_distance(hashes.ahash, rec.get("ahash", ""))
        p = hamming_distance(hashes.phash, rec.get("phash", ""))
        d = hamming_distance(hashes.dhash, rec.get("dhash", ""))
        if a is None or p is None or d is None:
            continue
        level = classify(a, p, d)
        if level is None:
            continue
        matches.append(Match(
            sha256=rec["sha256"],
            filename=rec.get("filename") or "unknown",
            first_seen=rec.get("first_seen") or "unknown",
            times_seen=int(rec.get("times_seen") or 1),
            ahash_distance=a, phash_distance=p, dhash_distance=d, level=level,
            origin=str(rec.get("origin") or ""),
        ))
    matches.sort(key=lambda m: (max(m.phash_distance, m.dhash_distance), m.phash_distance))
    return matches[:MAX_MATCHES]