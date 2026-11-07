"""POSANTRA | VERIQ - the 18-case test matrix from the product specification.

Test images are synthetic stand-ins generated in code. These tests show how
VERIQ treats the SIGNALS in each scenario; they do not show that VERIQ can
tell real photographs from fakes. Uncertain outcomes are explicitly allowed.
"""
import os
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont
from PIL.TiffImagePlugin import IFDRational

import config
from modules import claim_analyzer as ca
from modules import forensic_analyzer as fa
from modules import hash_engine as he
from modules import image_analyzer
from modules import metadata_analyzer as ma
from modules import ocr_engine
from modules import post_extractor as pe
from modules import security
from modules import source_research as sr
from modules import url_validator as uv
from modules import verdict_engine as ve

OK = config.STATUS_COMPLETED


# ----------------------------------------------------------------- helpers
def jpeg(exif=None, size=(96, 72), colour="red") -> bytes:
    kwargs = {"format": "JPEG"}
    if exif is not None:
        kwargs["exif"] = exif
    buf = BytesIO()
    Image.new("RGB", size, colour).save(buf, **kwargs)
    return buf.getvalue()


def png(size=(96, 72)) -> bytes:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 50, 40], fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def exif_with(make=None, model=None, software=None, gps=False) -> Image.Exif:
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
    if model:
        exif[0x0110] = model
    if software:
        exif[0x0131] = software
    if gps:
        ifd = exif.get_ifd(0x8825)
        ifd[1] = "N"
        ifd[2] = (IFDRational(18, 1), IFDRational(31, 1), IFDRational(144, 10))
        ifd[3] = "E"
        ifd[4] = (IFDRational(73, 1), IFDRational(51, 1), IFDRational(0, 1))
    return exif


def run(data: bytes, filename: str, ocr_text: str = "", meta=None):
    """Run the whole image pipeline the way app.py does (OCR stubbed unless given)."""
    validation = security.validate_upload(filename, data)
    if not validation.ok:
        return SimpleNamespace(validation=validation, verdict=None)
    info = image_analyzer.analyze_basic(data, validation.detected_mime)
    meta = meta or ma.analyze_metadata(data, validation.extension, use_exiftool=False)
    ocr = ocr_engine.OCRResult(status=OK, text=ocr_text, word_count=len(ocr_text.split()))
    forensics = fa.analyze_forensics(data)
    hashes = he.compute_hashes(data)
    verdict = ve.evaluate(meta, ocr, forensics, hashes, None)
    return SimpleNamespace(validation=validation, info=info, meta=meta, ocr=ocr,
                           forensics=forensics, hashes=hashes, verdict=verdict)


AI_TAGS = {
    "JUMBF:JUMDLabel": "c2pa",
    "CBOR:ActionsDigitalSourceType":
        "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
    "CBOR:ActionsSoftwareAgentName": "ChatGPT",
    "CBOR:Claim_Generator_InfoName": "OpenAI Media Service API",
}


def ev(stance, tier, etype=sr.TYPE_REPORT, domain="a.example"):
    return sr.Evidence(source_title="T", url=f"https://{domain}/x", domain=domain,
                       stance=stance, tier=tier, evidence_type=etype, explanation="because")


CLAIMS = [ca.Claim(id="c1", text="Earthquake hit Pune today")]


# ------------------------------------------------------ 1. genuine photograph
def test_01_photo_like_file_is_unverified_never_authentic():
    r = run(jpeg(exif_with("Canon", "EOS R5")), "photo.jpg")
    assert r.verdict.assessment == ve.UNVERIFIED
    assert r.verdict.assessment != ve.AUTHENTIC
    assert r.meta.found["Camera make"] == "Canon"


# ------------------------------------------------------- 2. edited photograph
def test_02_editing_software_tag_is_an_observation_not_a_verdict():
    r = run(jpeg(exif_with("Canon", "EOS R5", "Adobe Photoshop 25.0")), "edited.jpg")
    assert r.verdict.assessment in (ve.UNVERIFIED, ve.INSUFFICIENT_EVIDENCE)
    assert r.verdict.assessment != ve.MANIPULATED
    assert any("Photoshop" in f.text and f.weight == ve.OBSERVATION for f in r.verdict.findings)


# ----------------------------------------------------- 3. AI-generated image
def test_03a_ai_image_without_declaration_is_never_called_authentic():
    # VERIQ cannot detect undeclared AI images. Uncertain outcomes are acceptable.
    gradient = Image.linear_gradient("L").convert("RGB")
    buf = BytesIO()
    gradient.save(buf, format="PNG")
    r = run(buf.getvalue(), "generated.png")
    assert r.verdict.assessment in (ve.INSUFFICIENT_EVIDENCE, ve.UNVERIFIED)


def test_03b_ai_image_with_declared_credentials_is_flagged_with_caveats():
    meta = ma._build_result(ma._tags_from_exiftool(AI_TAGS), "ExifTool")
    r = run(png(), "generated.png", meta=meta)
    assert r.verdict.assessment == ve.MANIPULATED
    assert r.verdict.strength == ve.STRENGTH_MODERATE
    assert "not validated" in r.verdict.reason


# ------------------------------------------------------------ 4. screenshot
def test_04_screenshot_png_without_metadata_is_uncertain():
    r = run(png(), "Screenshot 2026-11-05.png")
    assert r.verdict.assessment in (ve.INSUFFICIENT_EVIDENCE, ve.UNVERIFIED)
    assert r.meta.found == {}


# ---------------------------------------------------------- 5/6/7. EXIF cases
def test_05_image_with_exif():
    r = run(jpeg(exif_with("Nikon", "D850")), "a.jpg")
    assert r.meta.found["Camera model"] == "D850"
    assert "Camera make" not in r.meta.absent


def test_06_image_without_exif_is_not_treated_as_suspicious():
    r = run(jpeg(), "a.jpg")
    assert "Camera make" in r.meta.absent
    assert any("not evidence of manipulation" in n for n in r.meta.notes)
    assert r.verdict.assessment != ve.MANIPULATED


def test_07_gps_is_reported_as_unreliable_metadata_not_uploader_location():
    r = run(jpeg(exif_with("Canon", "R5", gps=True)), "a.jpg")
    assert r.meta.gps is not None
    assert r.meta.gps["latitude"] == pytest.approx(18.5207, abs=1e-3)
    gps_findings = [f for f in r.verdict.findings if "GPS" in f.text]
    assert gps_findings and all(f.weight == ve.INFO for f in gps_findings)
    assert "do not show where the uploader is" in gps_findings[0].text


# ------------------------------------------------------ 8. image containing text
@pytest.mark.skipif(config.find_tool("tesseract") is None, reason="Tesseract not installed")
def test_08_image_containing_text_is_read_and_labelled_unverified():
    img = Image.new("RGB", (700, 160), "white")
    ImageDraw.Draw(img).text((20, 40), "HELLO VERIQ", fill="black",
                             font=ImageFont.load_default(size=64))
    buf = BytesIO()
    img.save(buf, format="PNG")
    ocr = ocr_engine.extract_text(buf.getvalue())
    assert ocr.status == OK
    # OCR is not guaranteed perfect: only assert on the verdict if text was read.
    if ocr.text:
        v = ve.evaluate(ma.analyze_metadata(buf.getvalue(), ".png", use_exiftool=False),
                        ocr, fa.analyze_forensics(buf.getvalue()),
                        he.compute_hashes(buf.getvalue()))
        assert v.assessment == ve.UNVERIFIED


# ------------------------------------------- 9/10/11. invalid/oversized/corrupt
def test_09_invalid_file_rejected():
    assert not run(b"just some text", "notes.png").validation.ok
    assert not run(b"GIF89a....", "anim.png").validation.ok


def test_10_oversized_file_rejected(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 500)
    r = run(jpeg(size=(300, 300), colour="blue") + os.urandom(2000), "big.jpg")
    assert not r.validation.ok
    assert any("exceeds" in e for e in r.validation.errors)


def test_11_corrupted_image_never_crashes_any_module():
    noisy = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
    buf = BytesIO()
    noisy.save(buf, format="JPEG")
    full = buf.getvalue()
    truncated = full[: len(full) // 2]

    assert security.validate_upload("c.jpg", truncated).ok          # header looks fine
    assert image_analyzer.analyze_basic(truncated, "image/jpeg").status == config.STATUS_FAILED
    assert he.compute_hashes(truncated).status == config.STATUS_FAILED
    assert ma.analyze_metadata(truncated, ".jpg", use_exiftool=False).status in (OK, config.STATUS_FAILED)
    assert fa.analyze_forensics(truncated).status in (OK, config.STATUS_FAILED)

    verdict = ve.evaluate(
        ma.analyze_metadata(truncated, ".jpg", use_exiftool=False),
        ocr_engine.OCRResult(status=config.STATUS_FAILED),
        fa.analyze_forensics(truncated),
        he.compute_hashes(truncated),
    )
    assert verdict.assessment in ve.ASSESSMENTS


# ------------------------------------------------------ 12/13/14/15. URL cases
def test_12_valid_public_url():
    info = uv.parse_url("https://x.com/someone/status/123")
    assert info.ok and info.platform_key == "x"


def test_13_invalid_url():
    for bad in ("not a url", "ftp://x.com/a", "http://127.0.0.1/", "javascript:alert(1)"):
        assert not uv.parse_url(bad).ok


def test_14_unsupported_platform_is_labelled_not_rejected():
    info = uv.parse_url("https://example.org/post/1")
    assert info.ok and info.platform_name == uv.UNKNOWN_PLATFORM


def test_15_inaccessible_url_gives_the_exact_fallback_message(monkeypatch):
    monkeypatch.setattr(pe, "_safe_get",
                        lambda *a: pe.FetchResult(False, error="The request timed out."))
    result = pe.extract(uv.parse_url("https://example.org/post/1"))
    assert result.status == config.STATUS_MANUAL
    assert result.fallback_message == (
        "Automatic retrieval was unavailable. You can provide the post text or "
        "upload a screenshot/image for investigation.")


# ------------------------------------------------------ 16/17/18. claim cases
def test_16_misleading_context_from_earlier_publication():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.CONTRADICTS, 4, etype=sr.TYPE_EARLIER)])
    assert v.assessment == ve.MISLEADING_CONTEXT
    assert "may be genuine" in v.reason


def test_17_contradicted_claim_needs_reliable_source():
    assert ve.evaluate_claims(CLAIMS, [ev(sr.CONTRADICTS, 1)]).assessment == ve.CONTRADICTED
    # the same stance from a social post or unknown site must not decide anything
    for tier in (0, 8, 9):
        assert ve.evaluate_claims(CLAIMS, [ev(sr.CONTRADICTS, tier)]).assessment == ve.UNVERIFIED


def test_18_insufficient_evidence_case():
    assert ve.evaluate_claims([], []).assessment == ve.INSUFFICIENT_EVIDENCE
    assert run(png(), "blank.png").verdict.assessment in (ve.INSUFFICIENT_EVIDENCE, ve.UNVERIFIED)