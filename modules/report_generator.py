"""POSANTRA | VERIQ - investigation report generation (Step 12).

Builds a JSON-serialisable report dictionary from analysis results, then
renders it as a standalone HTML document. Every value is HTML-escaped because
OCR text, post text and source details come from untrusted places. The report
carries a Content-Security-Policy that blocks scripts and remote loads, and
never embeds the uploaded image.
"""
from __future__ import annotations

import hashlib
import html
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

import config
from modules import claim_analyzer as ca
from modules import verdict_engine as ve

REPORT_VERSION = 1
REPORT_TITLE = "VERIQ Investigation Report"
REPORT_STATEMENT = (
    "This report represents an evidence-based technical assessment and should "
    "not be interpreted as absolute proof of authenticity or manipulation."
)
TYPE_IMAGE = "Image investigation"
TYPE_URL = "Post URL investigation"
NOT_AVAILABLE = "Not available"

COLOURS = {
    ve.AUTHENTIC: "#1a7f4b",
    ve.MANIPULATED: "#b42318",
    ve.CONTRADICTED: "#b42318",
    ve.MISLEADING_CONTEXT: "#a15c00",
    ve.UNVERIFIED: "#a15c00",
    ve.INSUFFICIENT_EVIDENCE: "#5b6572",
}


# ------------------------------------------------------------------ helpers
def new_investigation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"VQ-{stamp}-{secrets.token_hex(3).upper()}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _g(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default) if obj is not None else default


def url_input_hash(info: Any, manual: Any) -> str:
    """Hash of the submitted URL and/or user-provided text ('' if neither)."""
    parts = []
    if info is not None and _g(info, "ok", False):
        parts.append(info.normalized)
    if manual is not None and _g(manual, "status") == config.STATUS_COMPLETED:
        parts.append(manual.text)
    return _sha("\n".join(parts)) if parts else ""


def _verdict_dict(scope: str, short: str, verdict: Any) -> dict:
    return {
        "scope": scope,
        "short": short,
        "assessment": verdict.assessment,
        "strength": verdict.strength,
        "reason": verdict.reason,
        "findings": [{"area": f.area, "text": f.text, "weight": f.weight}
                     for f in verdict.findings],
        "limitations": list(verdict.limitations),
        "suggested_checks": list(verdict.suggested_checks),
        "context_checked": bool(verdict.context_checked),
    }


def _claims_list(claims: Optional[list]) -> list[dict]:
    return [{"id": c.id, "text": c.text, "source": c.source_label,
             "kinds": list(c.kinds), "dates": list(c.dates), "places": list(c.places),
             "relative": list(c.relative), "questions": list(c.questions)}
            for c in claims or []]


def _evidence_list(evidence: Optional[list]) -> list[dict]:
    return [{"source_title": e.source_title, "url": e.url, "domain": e.domain,
             "published": e.published, "retrieved": e.retrieved,
             "evidence_type": e.evidence_type, "claim": e.relevance, "stance": e.stance,
             "explanation": e.explanation, "tier": e.tier_label,
             "provider": e.provider, "added_by": e.added_by}
            for e in evidence or []]


def _comparison_dict(comparison: Optional[dict]) -> dict:
    if not comparison or not comparison.get("ok"):
        return {"available": False}
    exact = comparison.get("exact") or {}
    return {
        "available": True,
        "exact_seen_before": bool(exact),
        "first_seen": exact.get("first_seen"),
        "times_seen": exact.get("times_seen"),
        "similar_count": len(comparison.get("matches") or []),
        "total_compared": comparison.get("total", 0),
    }


def _provenance(cc: Optional[dict], evidence: list[dict], comparison: Optional[dict],
                post_published: str = "", published_by_user: bool = False) -> list[str]:
    out: list[str] = []
    if post_published:
        who = "supplied by the user" if published_by_user else "as reported by the source"
        out.append(f"Date shown on the post ({who}): {post_published}. Not independently verified.")
    if cc:
        kinds = ", ".join(cc.get("digital_source_types") or []) or "not stated"
        tool = cc.get("software_agent") or cc.get("generator") or "an unnamed tool"
        out.append(
            f"The file embeds Content Credentials (C2PA). Declared source type: {kinds}; "
            f"tool: {tool}. The signature was not validated, so this is a self-declared record."
        )
    dated = []
    for item in evidence:
        day = ca.parse_date(item.get("published"))
        if day:
            dated.append((day, item))
    if dated:
        _, item = min(dated, key=lambda pair: pair[0])
        out.append(
            f"Earliest publicly discovered source among the recorded evidence: "
            f"'{item.get('source_title')}' ({item.get('domain')}), dated "
            f"{item.get('published')} as reported."
        )
        out.append(
            "This may not be the true original. VERIQ only knows about the sources recorded "
            "in this investigation, and dates from the GDELT index show when it first saw an "
            "article, not necessarily when it was published."
        )
    if comparison and comparison.get("available"):
        if comparison.get("exact_seen_before"):
            out.append(
                f"A byte-identical file was analysed before by this installation "
                f"(first recorded {comparison.get('first_seen')} UTC). This says nothing "
                "about where the file came from."
            )
        if comparison.get("similar_count"):
            out.append(
                f"{comparison['similar_count']} visually similar image(s) exist in this "
                "installation's local history. Similar images may be unrelated look-alikes."
            )
    if not out:
        out.append("No provenance information was established in this investigation.")
    return out


def _limitations(assessments: list[dict], extra: list[str]) -> list[str]:
    items: list[str] = []
    for a in assessments:
        items += a.get("limitations") or []
    items += extra
    return list(dict.fromkeys(items))


def _add_headline(data: dict) -> None:
    a = data.get("assessments") or []
    data["headline"] = "; ".join(f"{x.get('short', '')}: {x.get('assessment', '')}" for x in a)
    data["strength_summary"] = "; ".join(f"{x.get('short', '')}: {x.get('strength', '')}" for x in a)


def headline(data: dict) -> tuple[str, str]:
    return data.get("headline", ""), data.get("strength_summary", "")


_LOCATION_NOTE = ("VERIQ does not determine the physical location of the person who uploaded "
                  "or published content.")


# ------------------------------------------------------------ image report
def build_image_report(report_id: str, validation: Any, info: Any, meta: Any, ocr: Any,
                       forensics: Any, hashes: Any, comparison: Optional[dict],
                       verdict: Any, claim_result: Optional[dict] = None) -> dict:
    cc = _g(meta, "content_credentials")
    comparison_d = _comparison_dict(comparison)
    claims = _claims_list(claim_result.get("claims")) if claim_result else []
    evidence = _evidence_list(claim_result.get("evidence")) if claim_result else []

    assessments = [_verdict_dict("Image technical assessment", "Image", verdict)]
    notes: list[str] = []
    if claim_result and claim_result.get("verdict") is not None:
        assessments.append(_verdict_dict(
            "Claim assessment (text found in the image)", "Claims", claim_result["verdict"]))
    else:
        notes.append("No claim investigation was performed because no text was extracted "
                     "from the image.")

    forensic_ok = _g(forensics, "status") == config.STATUS_COMPLETED
    data = {
        "report_version": REPORT_VERSION,
        "title": REPORT_TITLE,
        "investigation_id": report_id,
        "generated_utc": utc_now(),
        "investigation_type": TYPE_IMAGE,
        "input_hash": validation.sha256,
        "input_label": validation.safe_name,
        "input": [
            ["File name (sanitised)", validation.safe_name],
            ["Detected type", validation.detected_mime],
            ["Format (decoder)", _g(info, "format")],
            ["File size", f"{validation.size_bytes:,} bytes"],
            ["Dimensions", f"{_g(info, 'width', 0)} x {_g(info, 'height', 0)} px"],
            ["SHA-256", validation.sha256],
        ],
        "extracted": {
            "kind": "image",
            "ocr": {
                "status": _g(ocr, "status", NOT_AVAILABLE),
                "error": _g(ocr, "error"),
                "text": _g(ocr, "text", ""),
                "word_count": _g(ocr, "word_count", 0),
                "mean_confidence": _g(ocr, "mean_confidence"),
                "language": _g(ocr, "language", ""),
                "notes": list(_g(ocr, "notes") or []),
            },
            "content_credentials": cc,
        },
        "technical": {
            "kind": "image",
            "metadata": {
                "status": _g(meta, "status", NOT_AVAILABLE),
                "source": _g(meta, "source"),
                "error": _g(meta, "error"),
                "found": dict(_g(meta, "found") or {}),
                "absent": list(_g(meta, "absent") or []),
                "gps": _g(meta, "gps"),
                "notes": list(_g(meta, "notes") or []),
                "tag_count": len(_g(meta, "all_tags") or []),
            },
            "forensics": {
                "status": _g(forensics, "status", NOT_AVAILABLE),
                "error": _g(forensics, "error"),
                "indicators": [
                    {"name": i.name, "status": i.status, "summary": i.summary,
                     "significance": i.significance}
                    for i in (_g(forensics, "indicators") or [])
                ] if forensic_ok else [],
                "limitations": list(_g(forensics, "limitations") or []),
            },
            "fingerprints": {
                "status": _g(hashes, "status", NOT_AVAILABLE),
                "sha256": _g(hashes, "sha256", validation.sha256),
                "ahash": _g(hashes, "ahash", ""),
                "phash": _g(hashes, "phash", ""),
                "dhash": _g(hashes, "dhash", ""),
            },
            "local_comparison": comparison_d,
        },
        "claims": claims,
        "evidence": evidence,
        "provenance": _provenance(cc, evidence, comparison_d),
        "assessments": assessments,
        "notes": notes,
    }
    forensic_limits = data["technical"]["forensics"]["limitations"]
    data["limitations"] = _limitations(assessments, forensic_limits + [
        "The uploaded image is not stored and is not included in this report.",
        _LOCATION_NOTE,
    ])
    _add_headline(data)
    return data


# -------------------------------------------------------------- URL report
def build_url_report(report_id: str, info: Any, extraction: Any, manual: Any,
                     claim_result: Optional[dict] = None) -> dict:
    url_ok = info is not None and _g(info, "ok", False)
    manual_ok = manual is not None and _g(manual, "status") == config.STATUS_COMPLETED
    retrieved_ok = extraction is not None and _g(extraction, "status") == config.STATUS_COMPLETED

    if url_ok:
        rows = [["Submitted URL (normalised)", info.normalized],
                ["Detected platform", info.platform_name],
                ["Retrieval status", _g(extraction, "status", NOT_AVAILABLE)],
                ["Retrieval method", _g(extraction, "method") or "None"]]
        label = info.normalized
    elif info is not None:
        rows = [["Submitted text", _g(info, "submitted", "")],
                ["Result", "The URL was not accepted: " + " ".join(_g(info, "errors") or [])]]
        label = "URL not accepted"
    else:
        rows = [["Submitted URL", "No URL was submitted."]]
        label = "Text provided by user"
    if manual_ok:
        rows.append(["Text provided by user", "Yes (VERIQ cannot confirm it matches the original post)"])
        if not url_ok:
            label = "Text provided by user"

    retrieved = None
    if retrieved_ok:
        retrieved = {
            "method": extraction.method, "text": extraction.text, "title": extraction.title,
            "author": extraction.author, "author_url": extraction.author_url,
            "site_name": extraction.site_name, "published": extraction.published,
            "media_urls": list(extraction.media_urls), "notes": list(extraction.notes),
        }
    manual_d = None
    if manual_ok:
        manual_d = {"text": manual.text, "author": manual.author,
                    "published": manual.published, "notes": list(manual.notes)}

    claims = _claims_list(claim_result.get("claims")) if claim_result else []
    evidence = _evidence_list(claim_result.get("evidence")) if claim_result else []
    if claim_result and claim_result.get("verdict") is not None:
        claim_verdict = claim_result["verdict"]
    else:
        claim_verdict = ve.evaluate_claims([], [])
    assessments = [_verdict_dict("Claim assessment", "Claims", claim_verdict)]

    post_published = ""
    by_user = False
    if retrieved_ok and extraction.published:
        post_published = extraction.published
    elif manual_ok and manual.published:
        post_published, by_user = manual.published, True

    data = {
        "report_version": REPORT_VERSION,
        "title": REPORT_TITLE,
        "investigation_id": report_id,
        "generated_utc": utc_now(),
        "investigation_type": TYPE_URL,
        "input_hash": url_input_hash(info, manual),
        "input_label": label,
        "input": rows,
        "extracted": {"kind": "url", "retrieved": retrieved, "manual": manual_d},
        "technical": {
            "kind": "retrieval",
            "status": _g(extraction, "status", "Not applicable"),
            "method": _g(extraction, "method", ""),
            "error": _g(extraction, "error"),
            "attempts": list(_g(extraction, "attempts") or []),
            "notes": list(_g(extraction, "notes") or []),
        },
        "claims": claims,
        "evidence": evidence,
        "provenance": _provenance(None, evidence, None, post_published, by_user),
        "assessments": assessments,
        "notes": ["No file was analysed in this investigation. Technical image analysis "
                  "applies only to image investigations."],
    }
    data["limitations"] = _limitations(assessments, [
        "Text retrieved from a platform is a public preview that may be truncated, edited "
        "or removed. Attached images and videos were not analysed.",
        _LOCATION_NOTE,
    ])
    _add_headline(data)
    return data


# ------------------------------------------------------------------ HTML
class _Raw(str):
    """Trusted HTML produced by this module (already escaped)."""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _txt(value: Any) -> str:
    if value is None or value == "" or value == []:
        return NOT_AVAILABLE
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _cell(value: Any) -> str:
    return value if isinstance(value, _Raw) else _e(_txt(value))


def _kv(rows: list) -> str:
    body = "".join(f"<tr><th>{_e(k)}</th><td>{_cell(v)}</td></tr>" for k, v in rows)
    return f'<table class="kv">{body}</table>'


def _table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_cell(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _ul(items: list) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>" if items else ""


def _p(text: Any, cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    return f"<p{attr}>{_e(text)}</p>"


def _pre(text: Any) -> str:
    return f"<pre>{_e(text)}</pre>"


def _link(url: str) -> _Raw:
    if str(url).lower().startswith(("http://", "https://")):
        safe = _e(url)
        return _Raw(f'<a href="{safe}" rel="noopener noreferrer">{safe}</a>')
    return _Raw(_e(_txt(url)))


def _section(title: str, body: str) -> str:
    return f"<section><h2>{_e(title)}</h2>{body}</section>"


def _coord(value: Any) -> str:
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return NOT_AVAILABLE


_CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;color:#1c2128;background:#fff;margin:0;line-height:1.45}
main{max-width:900px;margin:0 auto;padding:28px 24px}
header.brand{border-bottom:2px solid #1c2128;padding-bottom:12px;margin-bottom:18px}
.brand .name{font-size:1.5rem;font-weight:700;letter-spacing:.06em}
.brand .cat{color:#5b6572;font-size:.9rem}
.brand .tag{color:#1a7f4b;font-weight:600;letter-spacing:.08em;font-size:.85rem}
h1{font-size:1.35rem;margin:.7rem 0 0}
h2{font-size:1.05rem;border-bottom:1px solid #d0d7de;padding-bottom:4px;margin-top:26px}
h3{font-size:.95rem;margin:14px 0 4px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:.88rem}
th,td{border:1px solid #d0d7de;padding:5px 8px;text-align:left;vertical-align:top;word-break:break-word}
th{background:#f3f4f6}
table.kv th{width:30%}
pre{white-space:pre-wrap;word-break:break-word;background:#f6f8fa;border:1px solid #d0d7de;padding:8px;font-size:.85rem}
.assess{border:1px solid #d0d7de;border-left:5px solid #5b6572;padding:10px 14px;margin:8px 0}
.assess .label{font-size:.72rem;letter-spacing:.12em;color:#5b6572;font-weight:600}
.assess .value{font-size:1.25rem;font-weight:700}
.note{color:#5b6572;font-size:.85rem}
.statement{border:1px solid #1c2128;padding:10px 14px;margin-top:14px;font-weight:600}
footer{margin-top:24px;color:#5b6572;font-size:.8rem}
@media print{main{padding:0}h2{page-break-after:avoid}tr{page-break-inside:avoid}}
"""


def _sec_extracted(ex: dict) -> str:
    out: list[str] = []
    if ex.get("kind") == "image":
        cc = ex.get("content_credentials")
        if cc:
            out.append("<h3>Content Credentials (C2PA) found</h3>")
            out.append(_kv([
                ["Declared source type", cc.get("digital_source_types")],
                ["Software agent", cc.get("software_agent")],
                ["Manifest generator", cc.get("generator")],
                ["Recorded actions", cc.get("actions")],
                ["Action timestamps", cc.get("when")],
            ]))
            out.append(_p("These are claims made by the file. VERIQ has not validated the "
                          "signature.", "note"))
        ocr = ex.get("ocr") or {}
        out.append("<h3>Extracted text (OCR)</h3>")
        out.append(_p(f"Status: {_txt(ocr.get('status'))}.", "note"))
        if ocr.get("text"):
            out.append(_pre(ocr["text"]))
            conf = ocr.get("mean_confidence")
            out.append(_p(f"Words read: {ocr.get('word_count', 0)}; mean confidence: "
                          f"{conf if conf is not None else 'n/a'}%; language model: "
                          f"{_txt(ocr.get('language'))}.", "note"))
        elif ocr.get("error"):
            out.append(_p(ocr["error"]))
        else:
            out.append(_p("No text was detected."))
        for note in ocr.get("notes") or []:
            out.append(_p(note, "note"))
    else:
        retrieved, manual = ex.get("retrieved"), ex.get("manual")
        if retrieved:
            out.append("<h3>Retrieved from the platform</h3>")
            out.append(_kv([
                ["Method", retrieved.get("method")], ["Title", retrieved.get("title")],
                ["Author / account", retrieved.get("author")],
                ["Author link", retrieved.get("author_url")],
                ["Site", retrieved.get("site_name")],
                ["Date as reported by the source", retrieved.get("published")],
            ]))
            out.append("<h3>Post text</h3>")
            out.append(_pre(retrieved["text"]) if retrieved.get("text") else _p("No post text was retrieved."))
            if retrieved.get("media_urls"):
                out.append("<h3>Media references (not downloaded)</h3>")
                out.append(_ul(retrieved["media_urls"]))
            for note in retrieved.get("notes") or []:
                out.append(_p(note, "note"))
        if manual:
            out.append("<h3>Text provided by the user</h3>")
            out.append(_kv([["Author / account", manual.get("author")],
                            ["Date shown on the post", manual.get("published")]]))
            out.append(_pre(manual.get("text")))
            for note in manual.get("notes") or []:
                out.append(_p(note, "note"))
        if not retrieved and not manual:
            out.append(_p("No post content was retrieved or provided."))
    return _section("2. Extracted information", "".join(out))


def _sec_technical(t: dict) -> str:
    out: list[str] = []
    if t.get("kind") == "image":
        m = t.get("metadata") or {}
        out.append("<h3>Metadata</h3>")
        out.append(_p(f"Status: {_txt(m.get('status'))}; source: {_txt(m.get('source'))}; "
                      f"embedded tags listed by the tool: {m.get('tag_count', 0)}.", "note"))
        if m.get("error"):
            out.append(_p(m["error"]))
        out.append("<h3>Metadata found</h3>")
        found = m.get("found") or {}
        out.append(_kv(list(found.items())) if found else _p("None of the key fields were found."))
        out.append("<h3>Metadata absent</h3>")
        out.append(_p(", ".join(m.get("absent") or []) or "All key fields were present."))
        gps = m.get("gps")
        out.append("<h3>GPS location (embedded metadata)</h3>")
        if gps:
            out.append(_p(f"Embedded coordinates: {_coord(gps.get('latitude'))}, "
                          f"{_coord(gps.get('longitude'))}. This is metadata stored inside the "
                          "file. It may be modified, copied from another file or unreliable, "
                          "and it does not show where the uploader is."))
            if gps.get("warning"):
                out.append(_p(gps["warning"]))
        else:
            out.append(_p("No GPS metadata was found."))
        for note in m.get("notes") or []:
            out.append(_p(note, "note"))

        f = t.get("forensics") or {}
        out.append("<h3>Forensic indicators</h3>")
        out.append(_p("Forensic indicators are technical observations, not proof of manipulation.", "note"))
        if f.get("indicators"):
            out.append(_table(["Indicator", "Status", "Finding", "Worth a closer look"],
                              [[i.get("name"), i.get("status"), i.get("summary"),
                                "Yes" if i.get("significance") == "observation" else "No"]
                               for i in f["indicators"]]))
        else:
            out.append(_p(f"Forensic analysis: {_txt(f.get('status'))}. {f.get('error') or ''}"))

        h = t.get("fingerprints") or {}
        out.append("<h3>Image fingerprints</h3>")
        out.append(_kv([["SHA-256", h.get("sha256")], ["aHash", h.get("ahash")],
                        ["pHash", h.get("phash")], ["dHash", h.get("dhash")]]))
        c = t.get("local_comparison") or {}
        out.append("<h3>Local comparison</h3>")
        if c.get("available"):
            out.append(_p(
                f"Compared against {c.get('total_compared', 0)} fingerprint(s) previously stored "
                f"by this installation. Byte-identical file seen before: "
                f"{'yes' if c.get('exact_seen_before') else 'no'}. Visually similar images "
                f"found: {c.get('similar_count', 0)}. This is not a reverse image search."))
        else:
            out.append(_p("The local comparison was not available."))
    else:
        out.append(_kv([["Retrieval status", t.get("status")], ["Method", t.get("method")],
                        ["Error", t.get("error")]]))
        if t.get("attempts"):
            out.append("<h3>Retrieval attempts</h3>")
            out.append(_ul(t["attempts"]))
        for note in t.get("notes") or []:
            out.append(_p(note, "note"))
    return _section("3. Technical analysis", "".join(out))


def _sec_claims(claims: list) -> str:
    intro = _p("Claim, Evidence, Context and Assessment are kept separate in this report. "
               "Candidate claims are proposed by simple pattern rules and are not "
               "judgements of truth.", "note")
    if not claims:
        return _section("4. Claims", intro + _p("No claim investigation was recorded, or no "
                                               "checkable statements were identified."))
    rows = [[c.get("id"), c.get("text"), c.get("kinds"), c.get("dates") or "-",
             c.get("places") or "-", c.get("source")] for c in claims]
    body = intro + _table(["ID", "Claim", "Looks like", "Dates in text", "Places (guess)", "Source"], rows)
    questions = []
    for c in claims:
        for q in c.get("questions") or []:
            questions.append(f"{c.get('id')}: {q}")
    if questions:
        body += "<h3>Questions requiring verification</h3>" + _ul(questions)
    return _section("4. Claims", body)


def _sec_evidence(evidence: list) -> str:
    if not evidence:
        return _section("5. Evidence and sources",
                        _p("No sources were recorded in this investigation."))
    rows = [[e.get("stance"), e.get("source_title"), e.get("domain"), e.get("tier"),
             e.get("evidence_type"), e.get("published"), e.get("retrieved"), e.get("claim"),
             e.get("explanation"), _link(e.get("url", ""))] for e in evidence]
    body = (_p("Stances and explanations were recorded by a person. VERIQ does not "
               "automatically judge sources. Source tiers are a rough guide based on the "
               "web domain.", "note")
            + _table(["Stance", "Source", "Domain", "Tier", "Type", "Published", "Retrieved",
                      "Claim", "Why it matters", "URL"], rows))
    return _section("5. Evidence and sources", body)


def _sec_assessment(assessments: list) -> str:
    out: list[str] = []
    for a in assessments:
        label = a.get("assessment")
        colour = COLOURS.get(label, "#5b6572")
        out.append(f"<h3>{_e(a.get('scope'))}</h3>")
        out.append(
            f'<div class="assess" style="border-left-color:{colour}">'
            f'<div class="label">ASSESSMENT</div>'
            f'<div class="value" style="color:{colour}">{_e(label)}</div></div>')
        out.append(f"<p><strong>Evidence strength:</strong> {_e(a.get('strength'))}</p>")
        out.append(f"<p><strong>Reason:</strong> {_e(a.get('reason'))}</p>")
        out.append(_p("Sources recorded with a stance and explanation were considered: "
                      + ("yes." if a.get("context_checked") else "no."), "note"))
        if a.get("findings"):
            out.append(_table(["Area", "Finding", "Weight"],
                              [[f.get("area"), f.get("text"), f.get("weight")]
                               for f in a["findings"]]))
        if a.get("suggested_checks"):
            out.append("<p><strong>Suggested manual checks</strong></p>" + _ul(a["suggested_checks"]))
    return _section("7. Assessment and evidence strength", "".join(out))


def render_html(data: dict) -> str:
    """Render a report dictionary as a standalone HTML document. Never raises on missing keys."""
    data = data or {}
    inv_id = data.get("investigation_id")
    header = (
        '<header class="brand">'
        f'<div class="name">{_e(config.PRODUCT_FULL_NAME)}</div>'
        f'<div class="cat">{_e(config.PRODUCT_CATEGORY)}</div>'
        f'<div class="tag">{_e(config.PRODUCT_TAGLINE)}</div>'
        f"<h1>{_e(REPORT_TITLE)}</h1></header>"
    )
    sections = [
        _section("1. Investigation details", _kv([
            ["Investigation ID", inv_id],
            ["Generated (UTC)", data.get("generated_utc")],
            ["Investigation type", data.get("investigation_type")],
        ]) + _kv(data.get("input") or [])),
        _sec_extracted(data.get("extracted") or {}),
        _sec_technical(data.get("technical") or {}),
        _sec_claims(data.get("claims") or []),
        _sec_evidence(data.get("evidence") or []),
        _section("6. Provenance findings", _ul(data.get("provenance") or [])
                 or _p("No provenance information was established.")),
        _sec_assessment(data.get("assessments") or []),
        _section("8. Limitations", _ul(data.get("limitations") or [])
                 + "".join(_p(n, "note") for n in data.get("notes") or [])),
        _section("9. Disclaimer", _p(config.DISCLAIMER)
                 + f'<div class="statement">{_e(REPORT_STATEMENT)}</div>'),
    ]
    footer = (f"<footer>Generated locally by {_e(config.PRODUCT_FULL_NAME)}. "
              f"Investigation ID: {_e(inv_id)}.</footer>")
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "style-src 'unsafe-inline'\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(REPORT_TITLE)} {_e(inv_id)}</title><style>{_CSS}</style></head>"
        f"<body><main>{header}{''.join(sections)}{footer}</main></body></html>"
    )