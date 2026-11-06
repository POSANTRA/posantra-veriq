from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

import config
from modules import ocr_engine


def png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def text_image(text: str = "HELLO VERIQ") -> bytes:
    img = Image.new("RGB", (700, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), text, fill="black", font=ImageFont.load_default(size=64))
    return png_bytes(img)


def test_parse_tsv_groups_words_into_lines():
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        "4\t1\t1\t1\t1\t0\t0\t0\t10\t10\t-1\t",
        "5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t96.0\tHello",
        "5\t1\t1\t1\t1\t2\t70\t10\t50\t20\t90.0\tworld",
        "5\t1\t1\t1\t2\t1\t10\t40\t50\t20\t80.0\tSecond",
        "5\t1\t1\t1\t2\t2\t70\t40\t50\t20\t-1\tjunk",
    ])
    lines, confs = ocr_engine._parse_tsv(tsv)
    assert lines == ["Hello world", "Second"]
    assert confs == [96.0, 90.0, 80.0]


def test_missing_tesseract_reports_not_available(monkeypatch):
    monkeypatch.setattr(config, "find_tool", lambda name: None)
    result = ocr_engine.extract_text(text_image())
    assert result.status == config.STATUS_NOT_AVAILABLE
    assert result.error


def test_invalid_language_rejected():
    result = ocr_engine.extract_text(text_image(), language="eng; calc")
    assert result.status == config.STATUS_FAILED


def test_preprocess_returns_valid_png():
    out = ocr_engine._preprocess(text_image())
    with Image.open(BytesIO(out)) as img:
        assert img.format == "PNG"
        assert img.mode == "L"


def test_preprocess_handles_transparency():
    rgba = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    out = ocr_engine._preprocess(png_bytes(rgba))
    with Image.open(BytesIO(out)) as img:
        assert img.getpixel((5, 5)) == 255  # transparent flattened to white


def test_corrupted_input_fails_gracefully():
    if config.find_tool("tesseract") is None:
        pytest.skip("Tesseract not installed")
    result = ocr_engine.extract_text(b"not an image")
    assert result.status == config.STATUS_FAILED


@pytest.mark.skipif(config.find_tool("tesseract") is None, reason="Tesseract not installed")
def test_real_ocr_reads_simple_text(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    result = ocr_engine.extract_text(text_image("HELLO VERIQ"))
    assert result.status == config.STATUS_COMPLETED
    # OCR is not guaranteed to be perfect: accept either word being recognised.
    assert "HELLO" in result.text.upper() or "VERIQ" in result.text.upper()
    assert list(tmp_path.iterdir()) == []  # temp file cleaned up


@pytest.mark.skipif(config.find_tool("tesseract") is None, reason="Tesseract not installed")
def test_blank_image_completes_without_text():
    blank = png_bytes(Image.new("RGB", (300, 200), "white"))
    result = ocr_engine.extract_text(blank)
    assert result.status == config.STATUS_COMPLETED
    assert result.text == ""
    assert any("No text was detected" in n for n in result.notes)