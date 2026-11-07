"""POSANTRA | VERIQ - attack and edge-case tests (Step 14)."""
import re
import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import config
from modules import claim_analyzer as ca
from modules import image_analyzer
from modules import metadata_analyzer as ma
from modules import ocr_engine
from modules import post_extractor as pe
from modules import security
from modules import url_validator as uv

ROOT = Path(__file__).resolve().parent.parent


def png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# -------------------------------------------------------------- upload attacks
def test_decompression_bomb_is_refused_without_crashing():
    bomb = png_bytes(Image.new("1", (12000, 12000)))      # 144 million pixels, tiny file
    assert len(bomb) < config.MAX_UPLOAD_BYTES
    assert security.validate_upload("bomb.png", bomb).ok  # passes the byte checks...
    info = image_analyzer.analyze_basic(bomb, "image/png")
    assert info.status == config.STATUS_FAILED            # ...but is refused by the pixel guard


def test_png_header_followed_by_html_is_not_decodable():
    polyglot = b"\x89PNG\r\n\x1a\n<html><script>alert(1)</script></html>"
    assert security.validate_upload("x.png", polyglot).ok
    assert image_analyzer.analyze_basic(polyglot, "image/png").status == config.STATUS_FAILED


@pytest.mark.parametrize("payload", [
    b"<html><body>hi</body></html>", b"%PDF-1.7 ...", b"MZ\x90\x00 fake exe",
    b"GIF89a....", b"BM....", b"PK\x03\x04 zip",
])
def test_non_image_content_renamed_to_png_is_rejected(payload):
    assert not security.validate_upload("holiday.png", payload).ok


@pytest.mark.parametrize("name", [
    "../../../etc/passwd.png", "..\\..\\Windows\\win.png", "a\x00b.png",
    "evil\u202egpj.png", "CON.png", "x" * 400 + ".png", "   .png", "....png",
])
def test_hostile_filenames_become_safe(name):
    safe = security.sanitize_filename(name)
    assert safe and len(safe) <= 100
    assert "/" not in safe and "\\" not in safe and "\x00" not in safe
    assert not safe.startswith(".")


def test_temp_files_are_always_cleaned_up(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    data = png_bytes(Image.new("RGB", (120, 90), "white"))
    ma.analyze_metadata(data, ".png", use_exiftool=True)
    ocr_engine.extract_text(data)
    ocr_engine.extract_text(b"corrupt")
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- URL attacks
@pytest.mark.parametrize("bad", [
    "https://x.com@evil.example/", "https://x.com:pass@evil.example/",
    "http://2130706433/", "http://localhost./", "http://[::ffff:7f00:1]/",
    "http://metadata.google.internal/", "https://example.com:22/",
])
def test_url_tricks_rejected(bad):
    assert not uv.parse_url(bad).ok


def test_dns_pointing_at_private_address_is_never_requested(monkeypatch):
    monkeypatch.setattr(uv.socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("a request was made to a private address")

    monkeypatch.setattr(pe.requests, "get", must_not_be_called)
    result = pe._safe_get("https://innocent-looking.example/p", "text/html", 1000)
    assert not result.ok


def test_hostile_page_content_is_handled_as_text(monkeypatch):
    html = ("<html><head><meta property='og:description' "
            "content='<script>alert(1)</script> flood \x00 hit Pune today'>"
            "</head></html>")
    monkeypatch.setattr(pe, "_safe_get",
                        lambda *a: pe.FetchResult(True, 200, "https://e.example/", "text/html", html.encode()))
    result = pe.extract(uv.parse_url("https://e.example/p"))
    assert result.status == config.STATUS_COMPLETED
    assert "\x00" not in result.text          # control characters removed
    # (the report and UI escape the remaining characters; see test_report/test_theme)


# --------------------------------------------------------------- big inputs
def test_claim_extraction_handles_huge_text_quickly():
    start = time.monotonic()
    claims = ca.extract_claims([("t", "Flood in Pune 12 " * 12000)])
    assert time.monotonic() - start < 5
    assert len(claims) <= ca.MAX_CLAIMS


def test_manual_text_is_capped():
    assert len(pe.from_manual("x" * 50_000).text) == pe.MAX_TEXT_CHARS


# ------------------------------------------------------------- source scans
def _project_sources():
    files = [ROOT / "app.py", ROOT / "config.py"]
    for folder in ("modules", "database"):
        files += sorted((ROOT / folder).glob("*.py"))
    return files


def test_no_shell_execution_or_dynamic_code_in_the_project():
    for path in _project_sources():
        text = path.read_text(encoding="utf-8")
        assert "shell=True" not in text, path
        assert "os.system" not in text, path
        assert "pickle" not in text, path
        assert not re.search(r"\b(eval|exec)\(", text), path


def test_product_name_is_never_changed():
    for path in _project_sources():
        text = path.read_text(encoding="utf-8")
        assert "VERITAS" not in text.upper(), path


def test_every_subprocess_call_uses_shell_false():
    for path in _project_sources():
        text = path.read_text(encoding="utf-8")
        calls = text.count("subprocess.run(")
        assert text.count("shell=False") >= calls, path