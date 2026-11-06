import os
from io import BytesIO

from PIL import Image

import config
from modules import image_analyzer


def make_image(fmt="PNG", size=(32, 24), mode="RGB") -> bytes:
    buf = BytesIO()
    Image.new(mode, size, "white").save(buf, format=fmt)
    return buf.getvalue()


def test_png_basic():
    info = image_analyzer.analyze_basic(make_image("PNG"), "image/png")
    assert info.status == config.STATUS_COMPLETED
    assert (info.width, info.height) == (32, 24)
    assert info.format == "PNG"
    assert info.has_alpha is False


def test_jpeg_basic():
    info = image_analyzer.analyze_basic(make_image("JPEG"), "image/jpeg")
    assert info.status == config.STATUS_COMPLETED
    assert info.format == "JPEG"


def test_webp_basic():
    info = image_analyzer.analyze_basic(make_image("WEBP"), "image/webp")
    assert info.status == config.STATUS_COMPLETED


def test_rgba_png_has_alpha():
    info = image_analyzer.analyze_basic(make_image("PNG", mode="RGBA"))
    assert info.status == config.STATUS_COMPLETED
    assert info.has_alpha is True


def test_garbage_bytes_fail_gracefully():
    info = image_analyzer.analyze_basic(b"not an image")
    assert info.status == config.STATUS_FAILED
    assert info.error


def test_truncated_jpeg_fails_gracefully():
    noisy = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
    buf = BytesIO()
    noisy.save(buf, format="JPEG")
    full = buf.getvalue()
    info = image_analyzer.analyze_basic(full[: len(full) // 2], "image/jpeg")
    assert info.status == config.STATUS_FAILED


def test_oversized_pixel_count_rejected(monkeypatch):
    monkeypatch.setattr(config, "MAX_IMAGE_PIXELS", 100)
    info = image_analyzer.analyze_basic(make_image("PNG", size=(32, 24)))
    assert info.status == config.STATUS_FAILED
    assert "safety limit" in info.error


def test_format_mismatch_rejected():
    info = image_analyzer.analyze_basic(make_image("PNG"), "image/jpeg")
    assert info.status == config.STATUS_FAILED