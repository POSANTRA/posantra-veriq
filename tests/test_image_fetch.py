from io import BytesIO

from PIL import Image

import config
from modules import image_fetch as imf
from modules import post_extractor as pe


def png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (20, 20), "red").save(buf, format="PNG")
    return buf.getvalue()


def fetched(body=b"", status=200, truncated=False):
    return pe.FetchResult(True, status, "https://c.example/a", "image/png", body, truncated)


def test_good_picture(monkeypatch):
    monkeypatch.setattr(pe, "_safe_get", lambda *a: fetched(png()))
    data, name, err = imf.fetch_post_image(["https://c.example/a.png"])
    assert data and name == "post_preview.png" and err is None


def test_non_image_and_errors_fall_through(monkeypatch):
    calls = iter([fetched(b"<html>login</html>"), pe.FetchResult(False, error="timed out")])
    monkeypatch.setattr(pe, "_safe_get", lambda *a: next(calls))
    data, name, err = imf.fetch_post_image(["https://a.example/x", "https://b.example/y"])
    assert data is None and "not a supported image" in err and "timed out" in err


def test_refused_and_oversized(monkeypatch):
    monkeypatch.setattr(pe, "_safe_get", lambda *a: fetched(status=403))
    assert "refused" in imf.fetch_post_image(["https://a.example/x"])[2]
    monkeypatch.setattr(pe, "_safe_get", lambda *a: fetched(png(), truncated=True))
    assert "size limit" in imf.fetch_post_image(["https://a.example/x"])[2]


def test_no_urls():
    assert imf.fetch_post_image([])[0] is None


def test_private_addresses_are_never_requested():
    data, _, err = imf.fetch_post_image(["http://127.0.0.1/x.png"])
    assert data is None and err