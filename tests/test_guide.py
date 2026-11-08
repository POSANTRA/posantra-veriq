from modules import metadata_analyzer as ma
from modules import verification_guide as vg


def meta(found=None, cc=None, status="Completed"):
    return ma.MetadataResult(status=status, found=found or {}, content_credentials=cc)


def test_guidance_shown_for_stripped_files():
    assert vg.needs_guidance(meta())
    assert vg.needs_guidance(None)
    assert vg.needs_guidance(meta(status="Failed"))


def test_guidance_hidden_when_provenance_exists():
    assert not vg.needs_guidance(meta(cc={"digital_source_types": []}))
    assert not vg.needs_guidance(meta({"Camera make": "Canon"}))


def test_message_makes_no_ai_claim():
    text = vg.NO_PROVENANCE_MESSAGE.lower()
    assert "cannot tell" in text
    assert "is ai-generated" not in text