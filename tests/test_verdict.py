import config
from modules import forensic_analyzer as fa
from modules import hash_engine as he
from modules import metadata_analyzer as ma
from modules import ocr_engine
from modules import verdict_engine as ve

OK = config.STATUS_COMPLETED


def meta(found=None, cc=None, gps=None, status=OK):
    return ma.MetadataResult(status=status, source="test", found=found or {},
                             content_credentials=cc, gps=gps)


def ocr(text="", status=OK):
    words = len(text.split())
    return ocr_engine.OCRResult(status=status, text=text, word_count=words)


def forensics(observation=False, status=OK):
    inds = [fa.Indicator("Error level analysis (ELA)", OK, "numbers", "",
                         "observation" if observation else "info")]
    return fa.ForensicResult(status=status, indicators=inds)


def hashes(status=OK):
    return he.HashResult(status=status, sha256="a" * 64, ahash="0" * 16,
                         phash="0" * 16, dhash="0" * 16)


AI_CC = {
    "generator": "OpenAI Media Service API",
    "software_agent": "ChatGPT gpt-image",
    "digital_source_types": ["AI-generated (trained algorithmic media)"],
    "actions": ["c2pa.created"],
    "when": [],
}


def scenarios():
    return {
        "empty": ve.evaluate(meta(), ocr(), forensics(), hashes()),
        "ai": ve.evaluate(meta(cc=AI_CC), ocr(), forensics(), hashes()),
        "camera": ve.evaluate(meta({"Camera make": "Canon", "Camera model": "R5"}),
                              ocr(), forensics(), hashes()),
        "editor": ve.evaluate(meta({ma.SOFTWARE_LABEL: "Adobe Photoshop 25"}),
                              ocr(), forensics(), hashes()),
        "ela": ve.evaluate(meta(), ocr(), forensics(observation=True), hashes()),
        "text": ve.evaluate(meta(), ocr("BREAKING earthquake in Pune"), forensics(), hashes()),
        "all_failed": ve.evaluate(meta(status=config.STATUS_FAILED),
                                  ocr(status=config.STATUS_NOT_AVAILABLE),
                                  forensics(status=config.STATUS_FAILED),
                                  hashes(status=config.STATUS_FAILED)),
        "none": ve.evaluate(None, None, None, None),
    }


def test_nothing_usable_is_insufficient_evidence():
    v = scenarios()["empty"]
    assert v.assessment == ve.INSUFFICIENT_EVIDENCE
    assert v.strength == ve.STRENGTH_INSUFFICIENT


def test_declared_ai_generation_is_manipulated_with_moderate_support():
    v = scenarios()["ai"]
    assert v.assessment == ve.MANIPULATED
    assert v.strength == ve.STRENGTH_MODERATE
    assert "not validated" in v.reason
    assert "intent" in v.reason
    assert any(f.weight == ve.INDICATES for f in v.findings)


def test_camera_metadata_alone_is_unverified_not_authentic():
    v = scenarios()["camera"]
    assert v.assessment == ve.UNVERIFIED
    assert v.assessment != ve.AUTHENTIC


def test_editing_software_alone_is_not_manipulated():
    v = scenarios()["editor"]
    assert v.assessment == ve.UNVERIFIED
    assert any("Photoshop" in f.text and f.weight == ve.OBSERVATION for f in v.findings)


def test_ela_observation_alone_is_not_manipulated():
    v = scenarios()["ela"]
    assert v.assessment == ve.UNVERIFIED
    assert any(f.area == "Forensic" for f in v.findings)


def test_text_makes_it_unverified_and_notes_unresearched_claims():
    v = scenarios()["text"]
    assert v.assessment == ve.UNVERIFIED
    assert any(f.area == "Text" and "not yet been researched" in f.text for f in v.findings)


def test_failed_components_are_listed_and_handled():
    for key in ("all_failed", "none"):
        v = scenarios()[key]
        assert v.assessment == ve.INSUFFICIENT_EVIDENCE
        assert "Metadata" in v.incomplete_components
        assert "did not complete" in v.reason


def test_history_matches_are_information_only():
    comparison = {"ok": True, "exact": {"first_seen": "x"}, "matches": [object()]}
    v = ve.evaluate(meta(), ocr(), forensics(), hashes(), comparison)
    assert v.assessment == ve.INSUFFICIENT_EVIDENCE
    assert any(f.area == "History" and f.weight == ve.INFO for f in v.findings)


def test_lone_image_never_claims_claim_based_verdicts():
    for name, v in scenarios().items():
        assert v.assessment in ve.ASSESSMENTS, name
        assert v.assessment not in (ve.AUTHENTIC, ve.CONTRADICTED, ve.MISLEADING_CONTEXT), name
        assert v.context_checked is False, name


def test_no_numeric_probabilities_in_output():
    for name, v in scenarios().items():
        assert "%" not in v.reason + v.strength, name


def test_limitations_always_present():
    for name, v in scenarios().items():
        assert any("Missing metadata is normal" in t for t in v.limitations), name


def test_ai_declaration_adds_signature_limitation():
    v = scenarios()["ai"]
    assert any("signature was not cryptographically validated" in t for t in v.limitations)