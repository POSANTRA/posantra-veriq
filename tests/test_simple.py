from modules import metadata_analyzer as ma
from modules import ocr_engine
from modules import simple_result as sr

OK = "Completed"


def meta(found=None, cc=None, status=OK):
    return ma.MetadataResult(status=status, found=found or {}, content_credentials=cc)


AI = {"digital_source_types": ["AI-generated (trained algorithmic media)"],
      "software_agent": "ChatGPT gpt-image", "generator": "OpenAI"}


def test_declared_ai():
    r = sr.simplify(meta(cc=AI))
    assert r.key == "ai" and "AI" in r.headline


def test_stripped_file_cannot_tell():
    r = sr.simplify(meta())
    assert r.key == "unknown"
    assert "nobody can honestly say" in r.sentence


def test_camera_is_never_called_real():
    r = sr.simplify(meta({"Camera make": "Canon"}))
    assert r.key == "camera"
    for text in (r.headline, r.sentence):
        assert "real photo." not in text.lower().replace("a real, untouched photo", "")
    assert r.certainty == "Clue, not proof"


def test_editing_app():
    assert sr.simplify(meta({ma.SOFTWARE_LABEL: "Adobe Photoshop 25"})).key == "edited"


def test_failed_metadata_is_unknown():
    assert sr.simplify(meta(status="Failed")).key == "unknown"
    assert sr.simplify(None).key == "unknown"


def test_text_and_history_bullets():
    ocr = ocr_engine.OCRResult(status=OK, text="Flood today")
    r = sr.simplify(meta(), ocr, {"ok": True, "exact": {"x": 1}})
    assert any("readable text" in t for _, t in r.bullets)
    assert any("checked this exact file" in t for _, t in r.bullets)