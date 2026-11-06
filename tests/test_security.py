import os
from io import BytesIO

from PIL import Image

import config
from modules import security


def make_image(fmt="PNG", size=(32, 24), mode="RGB") -> bytes:
    buf = BytesIO()
    Image.new(mode, size, "white").save(buf, format=fmt)
    return buf.getvalue()


def test_valid_png_jpeg_webp_pass():
    assert security.validate_upload("a.png", make_image("PNG")).ok
    assert security.validate_upload("a.jpg", make_image("JPEG")).ok
    assert security.validate_upload("a.jpeg", make_image("JPEG")).ok
    assert security.validate_upload("a.webp", make_image("WEBP")).ok


def test_empty_file_rejected():
    assert not security.validate_upload("a.png", b"").ok


def test_oversized_file_rejected(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    result = security.validate_upload("a.png", make_image("PNG", size=(200, 200)))
    assert not result.ok
    assert any("exceeds" in e for e in result.errors)


def test_bad_extension_rejected():
    result = security.validate_upload("a.gif", make_image("PNG"))
    assert not result.ok


def test_text_file_renamed_png_rejected():
    result = security.validate_upload("evil.png", b"this is not an image at all")
    assert not result.ok
    assert result.detected_mime is None


def test_extension_mismatch_rejected():
    result = security.validate_upload("photo.jpg", make_image("PNG"))
    assert not result.ok
    assert any("does not match" in e for e in result.errors)


def test_sanitize_path_traversal():
    assert security.sanitize_filename("../../etc/passwd") == "passwd"
    assert security.sanitize_filename("..\\..\\evil.png") == "evil.png"
    assert security.sanitize_filename("") == "upload"
    assert security.sanitize_filename("my photo<>.png") == "my_photo__.png"
    assert ".." not in security.sanitize_filename("....//x.png")


def test_sanitize_length_limited():
    assert len(security.sanitize_filename("a" * 500 + ".png")) <= 100


def test_sha256_present():
    result = security.validate_upload("a.png", make_image("PNG"))
    assert len(result.sha256) == 64


def test_temp_file_created_and_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    with security.secure_temp_file(b"hello", ".png") as path:
        assert path.exists()
        assert path.parent == tmp_path
        assert path.read_bytes() == b"hello"
        assert path.name.startswith("veriq_")
    assert not path.exists()


def test_temp_file_removed_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    captured = {}
    try:
        with security.secure_temp_file(b"x", ".png") as path:
            captured["p"] = path
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not captured["p"].exists()