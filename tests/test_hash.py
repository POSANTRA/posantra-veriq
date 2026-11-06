from io import BytesIO

from PIL import Image, ImageDraw

import config
from database import database as db
from modules import hash_engine as he


def to_bytes(img: Image.Image, fmt="PNG") -> bytes:
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def shapes_image(size=256) -> Image.Image:
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 120, 100], fill="black")
    d.ellipse([140, 60, 230, 200], fill="red")
    d.rectangle([40, 150, 110, 230], fill="blue")
    return img


def record_from(result: he.HashResult, sha="a" * 64) -> dict:
    return {
        "sha256": sha, "ahash": result.ahash, "phash": result.phash,
        "dhash": result.dhash, "filename": "old.png",
        "first_seen": "2026-01-01T00:00:00+00:00", "times_seen": 1,
    }


def test_hash_formats():
    r = he.compute_hashes(to_bytes(shapes_image()))
    assert r.status == config.STATUS_COMPLETED
    assert len(r.sha256) == 64
    for value in (r.ahash, r.phash, r.dhash):
        assert len(value) == 16
        int(value, 16)


def test_identical_images_have_zero_distance():
    a = he.compute_hashes(to_bytes(shapes_image()))
    b = he.compute_hashes(to_bytes(shapes_image()))
    assert he.hamming_distance(a.phash, b.phash) == 0
    assert he.hamming_distance(a.dhash, b.dhash) == 0


def test_resized_image_stays_close():
    original = shapes_image()
    resized = original.resize((512, 512), Image.LANCZOS)
    a = he.compute_hashes(to_bytes(original))
    b = he.compute_hashes(to_bytes(resized))
    assert he.hamming_distance(a.phash, b.phash) <= he.SIMILAR_MAX
    assert he.hamming_distance(a.dhash, b.dhash) <= he.SIMILAR_MAX


def test_clearly_different_images_not_near_identical():
    vertical = Image.linear_gradient("L").convert("RGB")
    horizontal = vertical.rotate(90)
    a = he.compute_hashes(to_bytes(vertical))
    b = he.compute_hashes(to_bytes(horizontal))
    level = he.classify(
        he.hamming_distance(a.ahash, b.ahash),
        he.hamming_distance(a.phash, b.phash),
        he.hamming_distance(a.dhash, b.dhash),
    )
    assert level != he.LEVEL_NEAR


def test_hamming_distance():
    assert he.hamming_distance("0000000000000000", "000000000000000f") == 4
    assert he.hamming_distance("00", "0000") is None
    assert he.hamming_distance("zz", "00") is None
    assert he.hamming_distance("", "00") is None


def test_blank_image_flagged_low_detail_and_never_matched():
    blank = he.compute_hashes(to_bytes(Image.new("RGB", (200, 200), "white")))
    assert blank.low_detail is True
    assert he.compare_to_records(blank, [record_from(blank)]) == []


def test_transparent_png_works():
    r = he.compute_hashes(to_bytes(Image.new("RGBA", (64, 64), (0, 0, 0, 0))))
    assert r.status == config.STATUS_COMPLETED


def test_corrupted_data_fails_gracefully():
    r = he.compute_hashes(b"not an image")
    assert r.status == config.STATUS_FAILED
    assert r.error


def test_compare_finds_similar_and_skips_exact_sha():
    original = he.compute_hashes(to_bytes(shapes_image()))
    resized = he.compute_hashes(to_bytes(shapes_image().resize((512, 512), Image.LANCZOS)))
    records = [
        record_from(resized, sha="b" * 64),
        record_from(original, sha=original.sha256),   # same file: handled as exact, not here
    ]
    matches = he.compare_to_records(original, records)
    assert len(matches) == 1
    assert matches[0].sha256 == "b" * 64
    assert matches[0].level in (he.LEVEL_NEAR, he.LEVEL_SIMILAR)


# ---------------------------------------------------------------- database
def test_database_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    assert db.count_fingerprints() == 0
    db.save_fingerprint("s" * 64, "0" * 16, "1" * 16, "2" * 16, "a.png", 10, 20)
    row = db.get_by_sha("s" * 64)
    assert row["filename"] == "a.png"
    assert row["times_seen"] == 1
    db.save_fingerprint("s" * 64, "0" * 16, "1" * 16, "2" * 16, "a.png", 10, 20)
    assert db.get_by_sha("s" * 64)["times_seen"] == 2
    assert db.count_fingerprints() == 1
    assert len(db.all_fingerprints()) == 1
    assert db.clear_fingerprints() == 1
    assert db.count_fingerprints() == 0


def test_database_is_injection_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    evil = "x'; DROP TABLE fingerprints; --"
    db.save_fingerprint("s" * 64, "0" * 16, "1" * 16, "2" * 16, evil, 1, 1)
    assert db.get_by_sha("s" * 64)["filename"] == evil
    assert db.count_fingerprints() == 1