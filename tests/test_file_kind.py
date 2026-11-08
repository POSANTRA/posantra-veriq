from types import SimpleNamespace as NS

import config
from modules import file_kind as fk
from modules import metadata_analyzer as ma

OK = config.STATUS_COMPLETED


def meta(found=None):
    return ma.MetadataResult(status=OK, found=found or {})


def info(w=1000, h=800, fmt="JPEG"):
    return NS(width=w, height=h, format=fmt)


def test_camera():
    k = fk.detect("a.jpg", info(), meta({"Camera make": "Canon"}))
    assert k.key == fk.CAMERA and not k.lost_info


def test_whatsapp_by_name():
    k = fk.detect("WhatsApp_Image_2026-09-18_at_9_10_48_PM.jpeg", info(1254, 1254), meta())
    assert k.key == fk.WHATSAPP and k.lost_info
    assert k.label.startswith("Looks like")


def test_screenshot_by_name_or_size():
    assert fk.detect("Screenshot_2026.png", info(500, 500, "PNG"), meta()).key == fk.SCREENSHOT
    assert fk.detect("x.png", info(1080, 2400, "PNG"), meta()).key == fk.SCREENSHOT


def test_known_size_alone_with_jpeg_is_not_enough():
    assert fk.detect("x.jpg", info(1920, 1080, "JPEG"), meta()).key == fk.UNKNOWN


def test_unknown_and_never_claims_is():
    k = fk.detect("photo.png", info(1086, 1448, "PNG"), meta())
    assert k.key == fk.UNKNOWN and not k.lost_info