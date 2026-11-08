import sqlite3

import config
from database import database as db
from modules import hash_engine as he
from modules import metadata_analyzer as ma
from modules import simple_result as sr

OK = config.STATUS_COMPLETED
AI = {"digital_source_types": ["AI-generated (trained algorithmic media)"],
      "software_agent": "ChatGPT", "generator": "OpenAI"}


def meta(found=None, cc=None):
    return ma.MetadataResult(status=OK, found=found or {}, content_credentials=cc)


def match(origin):
    return he.Match(sha256="b" * 64, filename="orig.png", first_seen="2026-11-05T10:00:00+00:00",
                    times_seen=1, ahash_distance=1, phash_distance=1, dhash_distance=1,
                    level=he.LEVEL_NEAR, origin=origin)


def test_origin_of():
    assert sr.origin_of(meta(cc=AI)) == "ai"
    assert sr.origin_of(meta(cc={"digital_source_types": []})) == "credentials"
    assert sr.origin_of(meta({"Camera make": "Canon"})) == "camera"
    assert sr.origin_of(meta()) == ""
    assert sr.origin_of(None) == ""


def test_copy_of_ai_image_is_a_hint_not_proof():
    r = sr.simplify(meta(), None, {"ok": True, "exact": None, "matches": [match("ai")]})
    assert r.key == "copy_ai"
    assert "not proof" in (r.sentence + r.certainty).lower()


def test_copy_of_camera_image_never_says_real():
    r = sr.simplify(meta(), None, {"ok": True, "exact": None, "matches": [match("camera")]})
    assert r.key == "copy_camera"
    assert "is real" not in r.sentence.lower()


def test_matches_without_origin_do_not_change_the_answer():
    r = sr.simplify(meta(), None, {"ok": True, "exact": None, "matches": [match("")]})
    assert r.key == "unknown"


def test_own_label_beats_a_history_match():
    r = sr.simplify(meta(cc=AI), None, {"ok": True, "exact": None, "matches": [match("camera")]})
    assert r.key == "ai"


def test_origin_is_stored_and_not_erased(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    s = "s" * 64
    db.save_fingerprint(s, "0" * 16, "1" * 16, "2" * 16, "a.png", 1, 1, "ai")
    db.save_fingerprint(s, "0" * 16, "1" * 16, "2" * 16, "a.png", 1, 1, "")   # re-upload, no origin
    assert db.get_by_sha(s)["origin"] == "ai"
    db.save_fingerprint("t" * 64, "0" * 16, "1" * 16, "2" * 16, "b.png", 1, 1, "bogus")
    assert db.get_by_sha("t" * 64)["origin"] == ""


def test_old_database_is_upgraded(monkeypatch, tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE fingerprints (sha256 TEXT PRIMARY KEY, ahash TEXT NOT NULL,
        phash TEXT NOT NULL, dhash TEXT NOT NULL, filename TEXT, width INTEGER, height INTEGER,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, times_seen INTEGER NOT NULL DEFAULT 1)""")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    db.save_fingerprint("s" * 64, "0" * 16, "1" * 16, "2" * 16, "a.png", 1, 1, "camera")
    assert db.get_by_sha("s" * 64)["origin"] == "camera"