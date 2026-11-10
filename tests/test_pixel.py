import os
from io import BytesIO

from PIL import Image

import config
from modules import pixel_forensics as pf
from modules import simple_result as sr
from modules import metadata_analyzer as ma


def to_bytes(img, fmt="PNG"):
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_smooth_image_gets_ai_like_clues():
    img = Image.linear_gradient("L").convert("RGB").resize((512, 512))
    r = pf.analyze(to_bytes(img))
    assert r.status == config.STATUS_COMPLETED
    assert r.ai_count >= 2


def test_noisy_image_gets_camera_like_grain():
    img = Image.frombytes("RGB", (320, 320), os.urandom(320 * 320 * 3))
    r = pf.analyze(to_bytes(img))
    assert r.status == config.STATUS_COMPLETED and r.camera_count >= 1


def test_screenshot_flag_stops_grain_penalty():
    img = Image.new("RGB", (400, 400), "white")
    r = pf.analyze(to_bytes(img), "screenshot")
    grain = next(s for s in r.signals if s.name == "Grain level")
    assert grain.lean == pf.NEUTRAL


def test_tiny_and_corrupt_inputs_do_not_crash():
    assert pf.analyze(to_bytes(Image.new("RGB", (40, 40)))).status == config.STATUS_NOT_AVAILABLE
    assert pf.analyze(b"not an image").status == config.STATUS_FAILED


def test_pixel_clues_alone_never_say_probably_ai_or_real():
    img = Image.linear_gradient("L").convert("RGB").resize((512, 512))
    pixel = pf.analyze(to_bytes(img))
    m = ma.MetadataResult(status=config.STATUS_COMPLETED, found={})
    r = sr.simplify(m, pixel=pixel)
    assert r.key != "ai_probable"
    assert "is real" not in (r.sentence + r.headline).lower()