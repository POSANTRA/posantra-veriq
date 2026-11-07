"""POSANTRA | VERIQ - visual theme and presentation helpers (Step 13).

Presentation only. Everything that can originate from an uploaded file or a
web page is HTML-escaped before it is placed in markup. Colours carry fixed
meanings: green = supportive, red = warning, amber = uncertain, grey = neutral.
"""
from __future__ import annotations

import html

import streamlit as st

import config
from modules import source_research as sr
from modules import verdict_engine as ve

GREEN, RED, AMBER, GREY = "#2ea36b", "#e5534b", "#d29922", "#8b949e"

ASSESSMENT_COLOURS = {
    ve.AUTHENTIC: GREEN,
    ve.MANIPULATED: RED,
    ve.CONTRADICTED: RED,
    ve.MISLEADING_CONTEXT: AMBER,
    ve.UNVERIFIED: AMBER,
    ve.INSUFFICIENT_EVIDENCE: GREY,
}
STANCE_COLOURS = {
    sr.SUPPORTS: GREEN,
    sr.CONTRADICTS: RED,
    sr.NEUTRAL: GREY,
    sr.NOT_ASSESSED: AMBER,
}

LOGO_SVG = (
    '<svg width="44" height="44" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" '
    'aria-hidden="true">'
    '<path d="M20 3 L35 11.5 V28.5 L20 37 L5 28.5 V11.5 Z" fill="none" '
    'stroke="#2ea36b" stroke-width="2"/>'
    '<path d="M12 15 L20 28 L28 15" fill="none" stroke="#f2f4f7" stroke-width="2.5" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

CSS = """
<style>
    .stApp { background: #0b0d10; }
    .block-container { padding-top: 4.5rem; max-width: 1200px; }
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stToolbar"], [data-testid="stDeployButton"] { display: none; }
    header[data-testid="stHeader"] { background: transparent; }

    .veriq-header {
        display: flex; align-items: center; gap: 1rem;
        border-bottom: 1px solid #262c34; padding-bottom: 1rem; margin-bottom: 1.5rem;
    }
    .veriq-title {
        font-size: 1.9rem; font-weight: 700; letter-spacing: 0.06em;
        color: #f2f4f7; margin: 0; line-height: 1.25;
    }
    .veriq-title .sep { color: #2ea36b; padding: 0 0.35rem; }
    .veriq-category { color: #8b949e; font-size: 0.92rem; margin: 0.1rem 0 0 0; }
    .veriq-tagline {
        color: #2ea36b; font-weight: 600; letter-spacing: 0.1em;
        font-size: 0.82rem; margin: 0.35rem 0 0 0;
    }

    .veriq-panel {
        background: #14181d; border: 1px solid #262c34;
        border-radius: 8px; padding: 0.9rem 1.2rem; margin-bottom: 1rem;
    }
    .veriq-panel h4 {
        margin: 0 0 0.5rem 0; font-size: 0.75rem; font-weight: 600;
        letter-spacing: 0.12em; text-transform: uppercase; color: #8b949e;
        border: none; padding: 0;
    }
    .status-ok  { color: #2ea36b; font-weight: 600; }
    .status-bad { color: #e5534b; font-weight: 600; }
    .muted { color: #8b949e; font-size: 0.85rem; }

    /* Section headings */
    .stMarkdown h4 {
        font-size: 0.95rem; font-weight: 600; letter-spacing: 0.1em;
        text-transform: uppercase; color: #c9d1d9;
        border-bottom: 1px solid #262c34; padding-bottom: 0.4rem;
        margin-top: 2rem;
    }

    /* Mode selector: restrained, not red */
    div[role="radiogroup"] label {
        padding: 6px 14px; border: 1px solid #262c34;
        border-radius: 6px; background: #14181d;
    }
    div[role="radiogroup"] label:hover { border-color: #2ea36b; }

    /* Tables, expanders */
    [data-testid="stTable"] table { border-color: #262c34; font-size: 0.9rem; }
    [data-testid="stTable"] th { background: #14181d; color: #8b949e; font-weight: 600; }
    [data-testid="stExpander"] { border: 1px solid #262c34; border-radius: 8px; }

    /* Verdict card */
    .verdict-box {
        background: #14181d; border: 1px solid #262c34; border-left: 5px solid #8b949e;
        border-radius: 8px; padding: 1rem 1.3rem; margin: 0.5rem 0 0.9rem 0;
    }
    .verdict-label {
        font-size: 0.72rem; letter-spacing: 0.14em; color: #8b949e; font-weight: 600;
    }
    .verdict-value { font-size: 1.7rem; font-weight: 700; letter-spacing: 0.04em; }
    .verdict-strength { margin-top: 0.5rem; }

    .vq-badge {
        display: inline-block; padding: 2px 10px; border-radius: 999px;
        font-size: 0.72rem; font-weight: 600; letter-spacing: 0.05em;
        border: 1px solid currentColor;
    }

    /* Source cards */
    .src-card {
        background: #14181d; border: 1px solid #262c34; border-left: 4px solid #8b949e;
        border-radius: 8px; padding: 0.8rem 1.1rem; margin-bottom: 0.7rem;
    }
    .src-title { font-weight: 600; color: #f2f4f7; margin: 0.35rem 0 0.15rem 0; }
    .src-meta { color: #8b949e; font-size: 0.82rem; }
    .src-why { margin-top: 0.4rem; font-size: 0.9rem; color: #d8dde3; }
    .src-link { font-size: 0.8rem; word-break: break-all; }
    .src-link a { color: #58a6ff; }
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def badge_html(text: str, colour: str) -> str:
    # colour is always one of this module's fixed constants.
    return f'<span class="vq-badge" style="color:{colour}">{_e(text)}</span>'


# ------------------------------------------------------------------- header
def header_html() -> str:
    return "".join([
        '<div class="veriq-header">',
        LOGO_SVG,
        "<div>",
        f'<p class="veriq-title">POSANTRA<span class="sep">|</span>VERIQ</p>',
        f'<p class="veriq-category">{_e(config.PRODUCT_CATEGORY)}</p>',
        f'<p class="veriq-tagline">{_e(config.PRODUCT_TAGLINE.upper())}</p>',
        "</div></div>",
    ])


def render_header() -> None:
    st.markdown(header_html(), unsafe_allow_html=True)


# -------------------------------------------------------------- tool status
@st.cache_data(show_spinner=False)
def _cached_tool_status() -> dict:
    return config.tool_status()


def render_tool_status() -> None:
    status = _cached_tool_status()
    labels = {"tesseract": "Tesseract OCR", "exiftool": "ExifTool"}
    rows = []
    for key, label in labels.items():
        info = status[key]
        if info["available"]:
            badge = '<span class="status-ok">● Available</span>'
            detail = _e(info["version"] or "")
        else:
            badge = '<span class="status-bad">● Not available</span>'
            detail = "Related analysis will be reported as not available."
        rows.append(
            f"<div>{badge} &nbsp; <b>{label}</b> <span class='muted'>{detail}</span></div>"
        )
    st.markdown(
        '<div class="veriq-panel"><h4>Analysis components</h4>' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------ verdict card
def verdict_card_html(assessment: str, strength: str) -> str:
    colour = ASSESSMENT_COLOURS.get(assessment, GREY)
    return (
        f'<div class="verdict-box" style="border-left-color:{colour}">'
        '<div class="verdict-label">ASSESSMENT</div>'
        f'<div class="verdict-value" style="color:{colour}">{_e(assessment)}</div>'
        f'<div class="verdict-strength">{badge_html(strength, colour)}</div>'
        "</div>"
    )


def render_verdict_card(assessment: str, strength: str) -> None:
    st.markdown(verdict_card_html(assessment, strength), unsafe_allow_html=True)


# ------------------------------------------------------------ source cards
def _safe_link(url: str) -> str:
    if str(url).lower().startswith(("http://", "https://")):
        safe = _e(url)
        return f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{safe}</a>'
    return _e(url)


def source_cards_html(evidence: list) -> str:
    cards = []
    for ev in evidence:
        colour = STANCE_COLOURS.get(ev.stance, GREY)
        meta = " · ".join(
            _e(x) for x in (ev.domain, ev.tier_label, ev.evidence_type) if x
        )
        dates = []
        if ev.published:
            dates.append(f"Published: {_e(ev.published)}")
        if ev.retrieved:
            dates.append(f"Retrieved: {_e(ev.retrieved)}")
        if ev.relevance:
            dates.append(f"Claim: {_e(ev.relevance)}")
        why = (f'<div class="src-why"><b>Why it matters:</b> {_e(ev.explanation)}</div>'
               if ev.explanation else "")
        cards.append(
            f'<div class="src-card" style="border-left-color:{colour}">'
            f"{badge_html(ev.stance, colour)}"
            f'<div class="src-title">{_e(ev.source_title)}</div>'
            f'<div class="src-meta">{meta}</div>'
            f'<div class="src-meta">{" · ".join(dates)}</div>'
            f"{why}"
            f'<div class="src-link">{_safe_link(ev.url)}</div>'
            "</div>"
        )
    return "".join(cards)


def render_source_cards(evidence: list) -> None:
    st.markdown(source_cards_html(evidence), unsafe_allow_html=True)