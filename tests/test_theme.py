from modules import source_research as sr
from modules import ui_theme as ut
from modules import verdict_engine as ve


def ev(**kw):
    base = dict(source_title="Title", url="https://reuters.com/a", domain="reuters.com",
                published="2026-11-05", retrieved="2026-11-06", stance=sr.SUPPORTS,
                tier=4, evidence_type=sr.TYPE_REPORT, explanation="because", relevance="c1")
    base.update(kw)
    return sr.Evidence(**base)


def test_source_cards_escape_hostile_content():
    html = ut.source_cards_html([ev(
        source_title="<script>alert(1)</script>",
        explanation="<img src=x onerror=alert(1)>",
        url='https://evil.example/a"onmouseover="x',
    )])
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert 'onmouseover="' not in html
    assert "&lt;script&gt;" in html


def test_dangerous_link_schemes_are_not_linked():
    html = ut.source_cards_html([ev(url="javascript:alert(1)")])
    assert "href=" not in html


def test_stance_colours_keep_fixed_meaning():
    assert ut.STANCE_COLOURS[sr.SUPPORTS] == ut.GREEN
    assert ut.STANCE_COLOURS[sr.CONTRADICTS] == ut.RED
    assert ut.STANCE_COLOURS[sr.NOT_ASSESSED] == ut.AMBER


def test_every_assessment_has_a_colour_and_card():
    for assessment in ve.ASSESSMENTS:
        assert assessment in ut.ASSESSMENT_COLOURS
        html = ut.verdict_card_html(assessment, ve.STRENGTH_LIMITED)
        assert assessment in html and ve.STRENGTH_LIMITED in html


def test_verdict_card_escapes_text():
    html = ut.verdict_card_html("<b>x</b>", "<i>y</i>")
    assert "<b>x</b>" not in html and "<i>y</i>" not in html


def test_header_contains_exact_branding():
    html = ut.header_html()
    assert "POSANTRA" in html and "VERIQ" in html
    assert "DETECT. INVESTIGATE. VERIFY." in html
    assert "VERITAS" not in html