import config
from modules import claim_analyzer as ca
from modules import post_extractor as pe
from modules import simple_post as sp
from modules import url_validator as uv
from modules import verdict_engine as ve

OK = config.STATUS_COMPLETED


def good_info():
    return uv.parse_url("https://example.com/p")


def extraction(text="Flood hit Chennai today.", **kw):
    return pe.PostExtraction(status=OK, method="m", text=text, **kw)


def claims_for(text):
    claims = ca.extract_claims([("t", text)])
    return {"claims": claims, "evidence": [], "verdict": ve.evaluate_claims(claims, [])}


def test_invalid_link():
    r = sp.simplify_post(uv.parse_url("http://127.0.0.1/"), None, None)
    assert r.key == "invalid"


def test_blocked_post_gives_fallback_advice():
    ex = pe.PostExtraction(status=config.STATUS_MANUAL, error="x")
    r = sp.simplify_post(good_info(), ex, None)
    assert r.key == "blocked" and any("paste" in s.lower() for s in r.next_steps)


def test_claims_found_never_says_true_or_fake():
    ex = extraction(published="5 Nov 2026")
    r = sp.simplify_post(good_info(), ex, None, claims_for(ex.text))
    assert r.key == "claims"
    words = (r.headline + r.sentence).lower()
    assert "cannot tell you if they are true" in words
    assert any("not verified" in t.lower() or "not been verified" in t.lower() or "has not verified" in t.lower()
               for _, t in r.bullets)


def test_no_claims():
    ex = extraction("good morning everyone, have a lovely day")
    assert sp.simplify_post(good_info(), ex, None, claims_for(ex.text)).key == "nothing"


def test_manual_text_works_without_url():
    manual = pe.from_manual("Flood hit Chennai today.")
    r = sp.simplify_post(None, None, manual, claims_for(manual.text))
    assert r.key == "claims"
    assert any("supplied" in t or "You supplied" in t for _, t in r.bullets)


def test_recorded_evidence_changes_the_card():
    from modules import source_research as sr
    ex = extraction()
    claims = ca.extract_claims([("t", ex.text)])
    evid = [sr.Evidence(source_title="T", url="https://reuters.com/a", domain="reuters.com",
                        stance=sr.CONTRADICTS, tier=4, evidence_type=sr.TYPE_REPORT,
                        explanation="because")]
    cr = {"claims": claims, "evidence": evid, "verdict": ve.evaluate_claims(claims, evid)}
    r = sp.simplify_post(good_info(), ex, None, cr)
    assert r.key == "evidence" and "wrong" in r.headline.lower()