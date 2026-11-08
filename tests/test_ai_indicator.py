import config
from modules import ai_indicator as ai
from modules import metadata_analyzer as ma
from modules import simple_result as sr

OK = config.STATUS_COMPLETED


def test_probability_from_different_label_styles():
    assert ai.ai_probability([{"label": "artificial", "score": 0.97}, {"label": "human", "score": 0.03}]) == 0.97
    assert abs(ai.ai_probability([{"label": "Real", "score": 0.2}]) - 0.8) < 1e-9
    assert ai.ai_probability([{"label": "cat", "score": 0.9}]) is None


def test_levels():
    assert ai.level_for(0.95) == ai.LEANS_AI
    assert ai.level_for(0.05) == ai.NO_SIGNS
    assert ai.level_for(0.5) == ai.UNSURE
    assert ai.level_for(None) == ai.UNSURE


def test_missing_libraries_are_reported_not_faked(monkeypatch):
    monkeypatch.setattr(ai, "available", lambda: False)
    assert ai.analyze(b"x").status == config.STATUS_NOT_AVAILABLE


def meta():
    return ma.MetadataResult(status=OK, found={}, content_credentials=None)


def test_hint_is_amber_and_never_real():
    hint = ai.AIIndicator(OK, ai.LEANS_AI, "m")
    r = sr.simplify(meta(), None, None, hint)
    assert r.key == "ai_hint" and r.colour == sr.AMBER
    assert "often wrong" in r.certainty.lower()


def test_no_signs_is_not_called_real():
    r = sr.simplify(meta(), None, None, ai.AIIndicator(OK, ai.NO_SIGNS, "m"))
    assert r.key == "unknown"
    assert "proves nothing" in " ".join(t for _, t in r.bullets)


def test_hint_never_overrides_a_real_label():
    ai_cc = {"digital_source_types": ["AI-generated (x)"], "software_agent": "T"}
    m = ma.MetadataResult(status=OK, found={}, content_credentials=ai_cc)
    assert sr.simplify(m, None, None, ai.AIIndicator(OK, ai.NO_SIGNS, "m")).key == "ai"