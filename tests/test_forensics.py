import os
from io import BytesIO

from PIL import Image
from PIL.PngImagePlugin import PngInfo

import config
from modules import forensic_analyzer as fa


def noisy_jpeg(quality=75, size=(160, 120)) -> bytes:
    img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def plain_png(info: PngInfo | None = None) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


def get(result, name):
    return next(i for i in result.indicators if i.name == name)


def test_zigzag_table_starts_correctly():
    assert fa._STD_LUMA_ZZ[:6] == [16, 11, 12, 14, 12, 10]


def test_quality_estimate_matches_pillow_quality():
    for q in (50, 75, 90):
        result = fa.analyze_forensics(noisy_jpeg(quality=q))
        quant = get(result, fa.NAME_QUANT)
        assert quant.status == config.STATUS_COMPLETED
        assert f"about {q}" in quant.summary


def test_jpeg_runs_ela_and_returns_heatmap():
    result = fa.analyze_forensics(noisy_jpeg())
    ela = get(result, fa.NAME_ELA)
    assert ela.status == config.STATUS_COMPLETED
    assert result.ela_png and result.ela_png.startswith(b"\x89PNG")


def test_png_marks_jpeg_checks_not_applicable():
    result = fa.analyze_forensics(plain_png())
    assert get(result, fa.NAME_JPEG_NA).status == config.STATUS_NOT_APPLICABLE
    assert get(result, fa.NAME_ELA).status == config.STATUS_NOT_APPLICABLE
    assert result.ela_png is None


def test_generator_chunk_names_detected_without_reading_values():
    info = PngInfo()
    info.add_text("parameters", "a secret prompt")
    result = fa.analyze_forensics(plain_png(info))
    chunk = get(result, fa.NAME_CHUNKS)
    assert chunk.significance == "observation"
    assert "parameters" in chunk.summary
    assert "secret prompt" not in chunk.summary + chunk.detail


def test_plain_png_has_no_generator_chunks():
    chunk = get(fa.analyze_forensics(plain_png()), fa.NAME_CHUNKS)
    assert chunk.significance == "info"


def test_ela_skipped_for_large_images(monkeypatch):
    monkeypatch.setattr(fa, "ELA_MAX_PIXELS", 100)
    result = fa.analyze_forensics(noisy_jpeg())
    assert get(result, fa.NAME_ELA).status == config.STATUS_NOT_AVAILABLE
    assert result.ela_png is None


def test_corrupted_data_fails_gracefully():
    result = fa.analyze_forensics(b"not an image")
    assert result.status == config.STATUS_FAILED
    assert result.error


def test_limitations_always_present():
    result = fa.analyze_forensics(plain_png())
    assert any("not proof" in text for text in result.limitations)