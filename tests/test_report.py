import hashlib
import json
import re
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

import config
from database import database as db
from modules import claim_analyzer as ca
from modules import forensic_analyzer as fa
from modules import hash_engine as he
from modules import image_analyzer
from modules import metadata_analyzer as ma
from modules import ocr_engine
from modules import post_extractor as pe
from modules import report_generator as rg
from modules import security
from modules import source_research as sr
from modules import url_validator as uv
from modules import verdict_engine as ve

OK = config.STATUS_COMPLETED


def png_bytes() -> bytes:
    img = Image.new("RGB", (200, 150), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 100, 80], fill="black")
    d.ellipse([110, 60, 190, 140], fill="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_evidence(title="Report", published="2026-11-05", url="https://reuters.com/a",
                  stance=sr.SUPPORTS):
    return sr.Evidence(source_title=title, url=url, domain="reuters.com", published=published,
                       stance=stance, tier=4, evidence_type=sr.TYPE_REPORT,
                       explanation="because", relevance="c1")


def image_report(text="Earthquake hit Pune today", evidence=None, with_claims=True):
    data = png_bytes()
    validation = security.validate_upload("a.png", data)
    info = image_analyzer.analyze_basic(data, "image/png")
    meta = ma.analyze_metadata(data, ".png", use_exiftool=False)
    ocr = ocr_engine.OCRResult(status=OK, text=text, word_count=len(text.split()),
                               mean_confidence=90.0, language="eng")
    forensics = fa.analyze_forensics(data)
    hashes = he.compute_hashes(data)
    comparison = {"ok": True, "exact": None, "matches": [], "total": 0}
    verdict = ve.evaluate(meta, ocr, forensics, hashes, comparison)
    claim_result = None
    if with_claims:
        claims = ca.extract_claims([("ocr", text)])
        ev = evidence or []
        claim_result = {"claims": claims, "evidence": ev,
                        "verdict": ve.evaluate_claims(claims, ev)}
    return rg.build_image_report("VQ-TEST", validation, info, meta, ocr, forensics, hashes,
                                 comparison, verdict, claim_result)


def test_id_format_and_uniqueness():
    a, b = rg.new_investigation_id(), rg.new_investigation_id()
    assert re.fullmatch(r"VQ-\d{8}-\d{6}-[0-9A-F]{6}", a)
    assert a != b


def test_image_report_has_required_content():
    data = image_report()
    assert data["investigation_type"] == rg.TYPE_IMAGE
    json.dumps(data)  # must be JSON-serialisable
    html = rg.render_html(data)
    for needle in (rg.REPORT_TITLE, rg.REPORT_STATEMENT, config.DISCLAIMER,
                   "POSANTRA | VERIQ", "Detect. Investigate. Verify.", "VQ-TEST",
                   "Technical analysis", "Provenance findings", "Limitations",
                   "Image technical assessment", "Claim assessment", "Evidence strength"):
        assert needle in html, needle


def test_hostile_content_is_escaped():
    text = "<script>alert(1)</script> flood hit Pune today."
    evidence = [make_evidence(title="<img src=x onerror=alert(1)>",
                              url='https://evil.example/a"onmouseover="x')]
    html = rg.render_html(image_report(text, evidence))
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert 'onmouseover="' not in html
    assert "&lt;script&gt;" in html


def test_report_blocks_scripts_with_csp():
    html = rg.render_html(image_report())
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html


def test_provenance_uses_earliest_discovered_wording():
    evidence = [make_evidence("Old", "2022-03-01", "https://reuters.com/old"),
                make_evidence("New", "2026-11-05", "https://reuters.com/new")]
    data = image_report(evidence=evidence)
    html = rg.render_html(data)
    assert "Earliest publicly discovered source" in html
    assert "2022-03-01" in " ".join(data["provenance"])
    assert "Original source" not in html
    assert "may not be the true original" in html


def test_report_without_claims_says_so():
    data = image_report(with_claims=False)
    assert len(data["assessments"]) == 1
    assert any("No claim investigation" in n for n in data["notes"])
    assert "Claims" not in data["headline"]


def test_headline_lists_both_assessments():
    head, strength = rg.headline(image_report())
    assert head.startswith("Image: ") and "; Claims: " in head
    assert strength


def test_report_never_embeds_image_data():
    html = rg.render_html(image_report())
    assert "data:image" not in html and "base64" not in html


def test_url_report_with_retrieved_content():
    info = uv.parse_url("https://example.com/p")
    extraction = pe.PostExtraction(status=OK, method="Page metadata (Open Graph)",
                                   text="Flood hit Chennai today.", published="2026-11-05")
    claims = ca.extract_claims([("post", extraction.text)])
    claim_result = {"claims": claims, "evidence": [],
                    "verdict": ve.evaluate_claims(claims, [])}
    data = rg.build_url_report("VQ-T", info, extraction, None, claim_result)
    assert data["investigation_type"] == rg.TYPE_URL
    assert data["input_hash"] == hashlib.sha256(info.normalized.encode()).hexdigest()
    html = rg.render_html(data)
    assert "Page metadata" in html and "Flood hit Chennai" in html
    assert "as reported by the source" in " ".join(data["provenance"])


def test_url_report_failed_retrieval_with_manual_text():
    info = uv.parse_url("https://www.instagram.com/p/x/")
    extraction = pe.PostExtraction(status=config.STATUS_MANUAL, error="No public content.",
                                   attempts=["login page"], fallback_message=pe.FALLBACK_MESSAGE)
    manual = pe.from_manual("Hundreds killed near Pune on 5 November 2026!", "me", "5 Nov")
    claims = ca.extract_claims([("manual", manual.text)])
    claim_result = {"claims": claims, "evidence": [],
                    "verdict": ve.evaluate_claims(claims, [], True)}
    data = rg.build_url_report("VQ-T", info, extraction, manual, claim_result)
    html = rg.render_html(data)
    assert "Text provided by the user" in html
    assert "supplied by the user" in " ".join(data["provenance"])
    assert data["input_hash"] == hashlib.sha256(
        (info.normalized + "\n" + manual.text).encode()).hexdigest()


def test_url_report_with_nothing_is_insufficient_evidence():
    data = rg.build_url_report("VQ-T", None, None, None, None)
    assert data["assessments"][0]["assessment"] == ve.INSUFFICIENT_EVIDENCE
    assert rg.url_input_hash(None, None) == ""
    rg.render_html(data)


def test_render_tolerates_empty_or_partial_data():
    assert isinstance(rg.render_html({}), str)
    assert isinstance(rg.render_html({"assessments": [{"assessment": "???"}]}), str)


# ---------------------------------------------------------------- database
def test_investigation_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    data = image_report()
    assert db.count_investigations() == 0
    db.save_investigation(data)
    assert db.count_investigations() == 1
    row = db.list_investigations()[0]
    assert row["id"] == "VQ-TEST" and "Image:" in row["assessment"]
    loaded = db.get_investigation("VQ-TEST")
    assert loaded["investigation_id"] == "VQ-TEST"
    assert "VQ-TEST" in rg.render_html(loaded)
    db.save_investigation(data)                 # upsert, not a duplicate
    assert db.count_investigations() == 1
    assert db.clear_investigations() == 1
    assert db.get_investigation("VQ-TEST") is None


def test_save_rejects_bad_records(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    with pytest.raises(ValueError):
        db.save_investigation({"investigation_type": "x"})
    monkeypatch.setattr(db, "MAX_RECORD_BYTES", 100)
    with pytest.raises(ValueError):
        db.save_investigation(image_report())


def test_record_storage_is_injection_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    data = image_report()
    data["investigation_id"] = "x'; DROP TABLE investigations; --"
    db.save_investigation(data)
    assert db.count_investigations() == 1