from modules import claim_analyzer as ca
from modules import source_research as sr
from modules import verdict_engine as ve

CLAIMS = [ca.Claim(id="c1", text="Earthquake hit Pune today")]


def ev(stance, tier, domain="a.example", etype=sr.TYPE_REPORT, expl="because"):
    return sr.Evidence(source_title="T", url=f"https://{domain}/x", domain=domain,
                       stance=stance, tier=tier, evidence_type=etype, explanation=expl)


def test_nothing_at_all_is_insufficient_evidence():
    assert ve.evaluate_claims([], []).assessment == ve.INSUFFICIENT_EVIDENCE


def test_claims_without_evidence_are_unverified():
    v = ve.evaluate_claims(CLAIMS, [])
    assert v.assessment == ve.UNVERIFIED
    assert v.strength == ve.STRENGTH_INSUFFICIENT
    assert v.context_checked is False


def test_reliable_contradiction():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.CONTRADICTS, 4)])
    assert (v.assessment, v.strength) == (ve.CONTRADICTED, ve.STRENGTH_MODERATE)
    v = ve.evaluate_claims(CLAIMS, [ev(sr.CONTRADICTS, 4, "a.example"), ev(sr.CONTRADICTS, 1, "b.example")])
    assert v.strength == ve.STRENGTH_HIGH


def test_reliable_support():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.SUPPORTS, 1)])
    assert (v.assessment, v.strength) == (ve.AUTHENTIC, ve.STRENGTH_MODERATE)
    assert "does not by itself show" in v.reason


def test_conflicting_reliable_evidence_is_unverified():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.SUPPORTS, 4, "a.example"), ev(sr.CONTRADICTS, 6, "b.example")])
    assert v.assessment == ve.UNVERIFIED
    assert "conflict" in v.reason


def test_weak_sources_never_decide():
    for tier in (0, 7, 8, 9):
        v = ve.evaluate_claims(CLAIMS, [ev(sr.SUPPORTS, tier), ev(sr.CONTRADICTS, tier, "b.example")])
        assert v.assessment == ve.UNVERIFIED, tier


def test_earlier_publication_gives_misleading_context():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.CONTRADICTS, 4, etype=sr.TYPE_EARLIER)])
    assert (v.assessment, v.strength) == (ve.MISLEADING_CONTEXT, ve.STRENGTH_MODERATE)
    assert "may be genuine" in v.reason


def test_unassessed_or_unexplained_evidence_is_ignored():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.NOT_ASSESSED, 1), ev(sr.SUPPORTS, 1, expl="  ")])
    assert v.assessment == ve.UNVERIFIED
    assert "not counted" in v.reason


def test_limitations_and_no_percentages():
    v = ve.evaluate_claims(CLAIMS, [ev(sr.SUPPORTS, 1)], user_provided_text=True)
    assert any("recorded by a person" in t for t in v.limitations)
    assert any("supplied by the user" in t for t in v.limitations)
    assert "%" not in v.reason + v.strength
    assert v.assessment in ve.ASSESSMENTS