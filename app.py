"""POSANTRA | VERIQ - Streamlit application.

Step 11 state: image investigation (validation, metadata, OCR, forensic
indicators, fingerprints, assessment, claims in image text) and post URL
retrieval with a manual fallback, claim analysis, evidence search and
claim assessment. Reports are added in a later step.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

import config
from database import database as local_db
from modules import (
    forensic_analyzer,
    hash_engine,
    image_analyzer,
    metadata_analyzer,
    ocr_engine,
    post_extractor,
    security,
    ui_claims,
    url_validator,
    verdict_engine,
)

st.set_page_config(
    page_title=config.PRODUCT_FULL_NAME,
    page_icon="🛡️",
    layout="wide",
)

# ------------------------------------------------------------------ Styling
CSS = """
<style>
    .block-container { padding-top: 4.5rem; max-width: 1200px; }
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stToolbar"], [data-testid="stDeployButton"] { display: none; }
    header[data-testid="stHeader"] { background: transparent; }

    .veriq-header {
        border-bottom: 1px solid #262c34;
        padding-bottom: 1rem;
        margin-bottom: 1.5rem;
    }
    .veriq-title {
        font-size: 2rem; font-weight: 700; letter-spacing: 0.06em;
        color: #f2f4f7; margin: 0; line-height: 1.3;
    }
    .veriq-title .sep { color: #2ea36b; padding: 0 0.35rem; }
    .veriq-category {
        color: #8b949e; font-size: 0.95rem; margin: 0.2rem 0 0 0;
    }
    .veriq-tagline {
        color: #2ea36b; font-weight: 600; letter-spacing: 0.08em;
        font-size: 0.9rem; margin-top: 0.4rem;
    }

    .veriq-panel {
        background: #14181d; border: 1px solid #262c34;
        border-radius: 6px; padding: 1rem 1.2rem; margin-bottom: 1rem;
    }
    .veriq-panel h4 {
        margin: 0 0 0.5rem 0; font-size: 0.8rem; font-weight: 600;
        letter-spacing: 0.1em; text-transform: uppercase; color: #8b949e;
    }
    .status-ok  { color: #2ea36b; font-weight: 600; }
    .status-bad { color: #e5534b; font-weight: 600; }
    .muted { color: #8b949e; font-size: 0.85rem; }

    .verdict-box {
        background: #14181d; border: 1px solid #262c34; border-left: 4px solid #8b949e;
        border-radius: 6px; padding: 1rem 1.2rem; margin-bottom: 0.8rem;
    }
    .verdict-label {
        font-size: 0.75rem; letter-spacing: 0.12em; color: #8b949e; font-weight: 600;
    }
    .verdict-value { font-size: 1.6rem; font-weight: 700; letter-spacing: 0.04em; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

VERDICT_COLOURS = {
    verdict_engine.AUTHENTIC: "#2ea36b",
    verdict_engine.MANIPULATED: "#e5534b",
    verdict_engine.CONTRADICTED: "#e5534b",
    verdict_engine.MISLEADING_CONTEXT: "#d29922",
    verdict_engine.UNVERIFIED: "#d29922",
    verdict_engine.INSUFFICIENT_EVIDENCE: "#8b949e",
}


# ------------------------------------------------------------------- Header
def render_header() -> None:
    st.markdown(
        f"""
        <div class="veriq-header">
            <p class="veriq-title">POSANTRA<span class="sep">|</span>VERIQ</p>
            <p class="veriq-category">{config.PRODUCT_CATEGORY}</p>
            <p class="veriq-tagline">{config.PRODUCT_TAGLINE.upper()}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------- Tool status UI
@st.cache_data(show_spinner=False)
def cached_tool_status() -> dict:
    return config.tool_status()


def render_tool_status() -> None:
    status = cached_tool_status()
    rows = []
    labels = {"tesseract": "Tesseract OCR", "exiftool": "ExifTool"}
    for key, label in labels.items():
        info = status[key]
        if info["available"]:
            badge = '<span class="status-ok">● Available</span>'
            detail = info["version"] or ""
        else:
            badge = '<span class="status-bad">● Not available</span>'
            detail = "Related analysis will be reported as not available."
        rows.append(
            f"<div>{badge} &nbsp; <b>{label}</b> "
            f"<span class='muted'>{detail}</span></div>"
        )
    st.markdown(
        '<div class="veriq-panel"><h4>Analysis components</h4>'
        + "".join(rows)
        + "</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------ Mode: image
def render_image_mode() -> None:
    st.subheader("Image Investigation")
    st.write("Upload a JPG, JPEG, PNG or WebP image.")

    remember = st.checkbox(
        "Remember this image's fingerprint locally so future uploads can be compared against it",
        value=True,
        help="Only hashes, the file name, dimensions and timestamps are stored on this "
        "machine. The image itself is never stored.",
    )

    uploaded = st.file_uploader(
        "Image",
        type=[ext.lstrip(".") for ext in sorted(config.ALLOWED_EXTENSIONS)],
        label_visibility="collapsed",
    )
    if uploaded is None:
        st.caption(f"Maximum file size: {config.MAX_UPLOAD_MB} MB.")
        return

    data = uploaded.getvalue()
    validation = security.validate_upload(uploaded.name, data)
    if not validation.ok:
        st.error("This file was rejected during validation.")
        for message in validation.errors:
            st.markdown(f"- {message}")
        return

    info = image_analyzer.analyze_basic(data, validation.detected_mime)
    if info.status != config.STATUS_COMPLETED:
        st.error(f"The image could not be analysed: {info.error}")
        return

    # Run every analysis first so the summary can be shown at the top.
    with st.spinner("Analysing image..."):
        meta = metadata_analyzer.analyze_metadata(data, validation.extension)
        ocr = ocr_engine.extract_text(data)
        forensics = forensic_analyzer.analyze_forensics(data)
        hashes = hash_engine.compute_hashes(data)

    comparison = None
    if hashes.status == config.STATUS_COMPLETED:
        comparison = get_local_comparison(hashes, validation, info, remember)

    verdict = verdict_engine.evaluate(meta, ocr, forensics, hashes, comparison)

    render_summary(verdict)
    render_media_information(data, validation, info)
    render_metadata(meta)
    render_ocr(ocr)
    render_forensics(forensics)
    render_hashes(hashes, comparison)

    if ocr.status == config.STATUS_COMPLETED and ocr.text:
        ui_claims.render_claim_investigation(
            [("Text extracted from the image (OCR)", ocr.text)],
            key_prefix="img",
            has_media=True,
            heading="Context Investigation: Claims in the Image Text",
        )


# ------------------------------------------------------------------ Summary
def render_summary(verdict) -> None:
    st.markdown("#### Investigation Summary")
    colour = VERDICT_COLOURS.get(verdict.assessment, "#8b949e")
    # Only the fixed assessment label is placed in HTML. Everything derived from
    # the uploaded file is rendered as plain text below.
    st.markdown(
        f'<div class="verdict-box" style="border-left-color:{colour}">'
        f'<div class="verdict-label">ASSESSMENT</div>'
        f'<div class="verdict-value" style="color:{colour}">{verdict.assessment}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**Evidence strength:** {verdict.strength}")
    st.markdown("**Reason**")
    st.write(verdict.reason)

    if verdict.findings:
        st.markdown("**Findings behind this assessment**")
        st.table(
            [{"Area": f.area, "Finding": f.text, "Weight": f.weight} for f in verdict.findings]
        )
    else:
        st.caption("No findings were recorded.")

    with st.expander("Limitations of this assessment"):
        for text in verdict.limitations:
            st.markdown(f"- {text}")
    with st.expander("Suggested manual checks"):
        for text in verdict.suggested_checks:
            st.markdown(f"- {text}")

    if not verdict.context_checked:
        st.caption("Claim and context research: not performed in this investigation.")


def render_media_information(data: bytes, validation, info) -> None:
    st.markdown("#### Media Information")
    left, right = st.columns([1, 2])
    with left:
        st.image(data, use_container_width=True)
    with right:
        rows = [
            ("File name", validation.safe_name),
            ("Detected type", validation.detected_mime),
            ("Format (decoder)", info.format),
            ("File size", f"{validation.size_bytes:,} bytes"),
            ("Dimensions", f"{info.width} x {info.height} px"),
            ("Megapixels", str(info.megapixels)),
            ("Colour mode", f"{info.mode} ({info.channels} channels)"),
            ("Transparency", "Yes" if info.has_alpha else "No"),
            ("Animated", f"Yes ({info.frames} frames)" if info.animated else "No"),
            (
                "Average colour (RGB)",
                str(info.mean_rgb) if info.mean_rgb else "Not available",
            ),
        ]
        st.table([{"Field": k, "Value": v} for k, v in rows])
        st.markdown("**SHA-256**")
        st.code(validation.sha256, language=None)
    st.caption("Validation passed. This image was decoded locally and is not stored.")


def render_metadata(meta) -> None:
    st.markdown("#### Metadata")

    if meta.status != config.STATUS_COMPLETED:
        st.warning(f"Metadata analysis: {meta.status}. {meta.error or ''}")
        return

    st.caption(f"Status: {meta.status}  |  Source: {meta.source}")

    cc = meta.content_credentials
    if cc:
        st.markdown("**Content Credentials (C2PA) found**")
        ai_declared = any("AI" in s for s in cc["digital_source_types"])
        message = (
            "The file carries an embedded provenance manifest"
            + (" that declares AI-generated content" if ai_declared else "")
            + ". VERIQ reads these claims but has not validated the signature."
        )
        (st.warning if ai_declared else st.info)(message)
        rows = [
            ("Declared source type", ", ".join(cc["digital_source_types"]) or "Not stated"),
            ("Software agent", cc["software_agent"] or "Not stated"),
            ("Manifest generator", cc["generator"] or "Not stated"),
            ("Recorded actions", ", ".join(cc["actions"]) or "Not stated"),
            ("Action timestamps", ", ".join(cc["when"]) or "Not stated"),
        ]
        st.table([{"Field": k, "Value": v} for k, v in rows])

    st.markdown("**Metadata found**")
    if meta.found:
        st.table([{"Field": k, "Value": v} for k, v in meta.found.items()])
    else:
        st.write("None of the key fields below were found.")

    st.markdown("**Metadata absent**")
    if meta.absent:
        st.write(", ".join(meta.absent))
    else:
        st.write("All key fields were present.")

    st.markdown("**GPS location (embedded metadata)**")
    if meta.gps:
        st.warning(
            f"Embedded coordinates: {meta.gps['latitude']:.6f}, {meta.gps['longitude']:.6f}. "
            "This is metadata stored inside the file. It may be modified, copied from "
            "another file or unreliable, and it does not show where the uploader is."
        )
        if meta.gps["warning"]:
            st.error(meta.gps["warning"])
    else:
        st.write("No GPS metadata was found.")

    for note in meta.notes:
        st.caption(note)

    if meta.all_tags:
        with st.expander(f"All embedded tags ({len(meta.all_tags)})"):
            st.dataframe(meta.all_tags, hide_index=True)


def render_ocr(ocr) -> None:
    st.markdown("#### OCR")
    st.caption(f"Status: {ocr.status}")

    if ocr.status == config.STATUS_NOT_AVAILABLE:
        st.warning(ocr.error or "OCR is not available.")
        return
    if ocr.status == config.STATUS_FAILED:
        st.error(f"OCR failed: {ocr.error}")
        return

    if ocr.text:
        st.markdown("**Extracted text**")
        st.code(ocr.text, language=None)
        col1, col2, col3 = st.columns(3)
        col1.metric("Words read", ocr.word_count)
        col2.metric(
            "Mean confidence",
            f"{ocr.mean_confidence}%" if ocr.mean_confidence is not None else "n/a",
        )
        col3.metric("Language model", ocr.language)
    else:
        st.write("No text was detected.")

    for note in ocr.notes:
        st.caption(note)


def render_forensics(result) -> None:
    st.markdown("#### Forensic Indicators")

    if result.status != config.STATUS_COMPLETED:
        st.error(f"Forensic analysis: {result.status}. {result.error or ''}")
        return

    st.caption(
        "Forensic indicators are technical observations, not proof of manipulation."
    )
    st.table(
        [
            {
                "Indicator": ind.name,
                "Status": ind.status,
                "Finding": ind.summary,
                "Worth a closer look": "Yes" if ind.significance == "observation" else "No",
            }
            for ind in result.indicators
        ]
    )

    with st.expander("What each indicator means"):
        for ind in result.indicators:
            if ind.detail:
                st.markdown(f"**{ind.name}.** {ind.detail}")

    if result.ela_png:
        with st.expander("ELA heatmap (brighter = larger change when re-saved)"):
            st.image(result.ela_png, use_container_width=True)

    st.markdown("**Limitations**")
    for text in result.limitations:
        st.caption(text)


# ------------------------------------------------- Fingerprints and history
def get_local_comparison(hashes, validation, info, remember: bool) -> dict:
    """Compare against local history once per image per session, then save.

    The comparison is computed BEFORE saving and cached, so Streamlit reruns
    never report an image as a "previous" sighting of itself.
    """
    cache = st.session_state.setdefault("veriq_cmp", {})
    saved = st.session_state.setdefault("veriq_saved", set())
    sha = hashes.sha256

    if sha not in cache:
        try:
            exact = local_db.get_by_sha(sha)
            records = local_db.all_fingerprints()
            cache[sha] = {
                "ok": True,
                "exact": exact,
                "matches": hash_engine.compare_to_records(hashes, records),
                "total": len(records),
            }
        except sqlite3.Error:
            cache[sha] = {"ok": False}

    result = cache[sha]
    result["saved"] = sha in saved
    if remember and result["ok"] and sha not in saved:
        try:
            local_db.save_fingerprint(
                sha, hashes.ahash, hashes.phash, hashes.dhash,
                validation.safe_name, info.width, info.height,
            )
            saved.add(sha)
            result["saved"] = True
        except sqlite3.Error:
            result["save_failed"] = True
    return result


def render_hashes(hashes, comparison) -> None:
    st.markdown("#### Image Fingerprints and Local Comparison")

    if hashes.status != config.STATUS_COMPLETED or comparison is None:
        st.error(f"Fingerprinting: {hashes.status}. {hashes.error or ''}")
        return

    st.caption(f"Status: {hashes.status}")
    st.table(
        [
            {"Hash": "SHA-256 (exact file)", "Value": hashes.sha256},
            {"Hash": "aHash (average)", "Value": hashes.ahash},
            {"Hash": "pHash (perceptual)", "Value": hashes.phash},
            {"Hash": "dHash (difference)", "Value": hashes.dhash},
        ]
    )
    for note in hashes.notes:
        st.caption(note)

    st.markdown("**Local comparison**")

    if not comparison["ok"]:
        st.warning("The local fingerprint history could not be read, so no comparison was made.")
        return

    exact = comparison["exact"]
    if exact:
        st.info(
            f"A byte-identical file (same SHA-256) was analysed before by this VERIQ "
            f"installation. First recorded: {exact['first_seen']} UTC, as "
            f"'{exact['filename']}', {exact['times_seen']} time(s). This shows only that "
            "VERIQ has seen this file before. It says nothing about where the file came from."
        )

    matches = comparison["matches"]
    if matches:
        st.warning(
            "Visually similar images were found in this installation's history. "
            "Similar images may be copies, resized versions or unrelated look-alikes, "
            "so compare them yourself."
        )
        st.table(
            [
                {
                    "Similarity": m.level,
                    "pHash distance": m.phash_distance,
                    "dHash distance": m.dhash_distance,
                    "aHash distance": m.ahash_distance,
                    "Recorded name": m.filename,
                    "First recorded (UTC)": m.first_seen,
                }
                for m in matches
            ]
        )
        st.caption("Distances count differing bits out of 64. Smaller means more similar.")
    elif not exact:
        st.write(
            f"No visually similar image was found among {comparison['total']} "
            "locally stored fingerprint(s)."
        )

    if comparison.get("save_failed"):
        st.caption("The fingerprint could not be saved locally.")
    elif comparison["saved"]:
        st.caption("This image's fingerprint (hashes only, not the image) is saved locally.")
    else:
        st.caption("This image's fingerprint was not saved.")

    st.caption(
        "Comparison covers only images analysed by this installation. It is not a "
        "reverse image search of the internet, so \"no match\" does not mean the image "
        "is original. Wider reverse-image research is an optional future integration."
    )


def clear_local_history() -> None:
    try:
        removed = local_db.clear_fingerprints()
    except sqlite3.Error:
        st.error("The local history could not be cleared.")
        return
    st.session_state.pop("veriq_cmp", None)
    st.session_state.pop("veriq_saved", None)
    st.success(f"Cleared {removed} stored fingerprint(s). Re-upload an image to refresh results.")


# -------------------------------------------------------------- Mode: URL
def run_url_retrieval(raw: str) -> dict:
    info = url_validator.parse_url(raw)
    extraction = post_extractor.extract(info) if info.ok else None
    return {"info": info, "extraction": extraction}


def render_url_mode() -> None:
    st.subheader("Post URL Investigation")
    st.write("Enter a public social-media post URL.")

    with st.form("veriq_url_form"):
        raw = st.text_input(
            "Public post URL",
            placeholder="https://...",
            max_chars=url_validator.MAX_URL_LENGTH,
        )
        submitted = st.form_submit_button("Retrieve public information")
    st.caption(
        "VERIQ requests the address from this machine, so the site (and, for X, YouTube "
        "and TikTok, that platform's public oEmbed service) can see the request. It never "
        "logs in or bypasses access restrictions."
    )

    if submitted:
        with st.spinner("Retrieving publicly available information..."):
            st.session_state["veriq_post"] = run_url_retrieval(raw)

    state = st.session_state.get("veriq_post")
    needs_fallback = True
    if state:
        render_post_result(state)
        extraction = state["extraction"]
        needs_fallback = extraction is None or extraction.status != config.STATUS_COMPLETED

    render_manual_fallback(expanded=bool(state) and needs_fallback)

    manual = st.session_state.get("veriq_manual")
    if manual is not None:
        if manual.status == config.STATUS_COMPLETED:
            render_extracted_content(manual, "Text Provided by You")
        else:
            st.warning(manual.error or "No text was provided.")

    sources, published, has_media, user_provided = [], "", False, False
    if (
        state
        and state["extraction"] is not None
        and state["extraction"].status == config.STATUS_COMPLETED
    ):
        ex = state["extraction"]
        parts = [p for p in (ex.title, ex.text) if p]
        if len(parts) == 2 and parts[0] == parts[1]:
            parts = parts[:1]
        if parts:
            sources.append(("Retrieved post", "\n".join(parts)))
        published, has_media = ex.published, bool(ex.media_urls)
    if manual is not None and manual.status == config.STATUS_COMPLETED:
        sources.append(("Text provided by you", manual.text))
        published = published or manual.published
        user_provided = True
    if sources:
        ui_claims.render_claim_investigation(
            sources,
            key_prefix="url",
            published=published,
            has_media=has_media,
            user_provided=user_provided,
        )
    elif state or manual is not None:
        st.info("No post text is available to investigate. Use the manual text box above.")


def render_post_result(state: dict) -> None:
    info = state["info"]
    extraction = state["extraction"]

    st.markdown("#### URL Information")
    if not info.ok:
        st.error("This URL was not accepted.")
        for message in info.errors:
            st.markdown(f"- {message}")
        return

    st.table(
        [
            {"Field": "Submitted URL (normalised)", "Value": info.normalized},
            {"Field": "Detected platform", "Value": info.platform_name},
            {"Field": "Retrieval status", "Value": extraction.status},
            {"Field": "Retrieval method", "Value": extraction.method or "None"},
        ]
    )
    for note in info.notes:
        st.caption(note)

    if extraction.attempts:
        with st.expander("Retrieval attempts"):
            for attempt in extraction.attempts:
                st.text(attempt)

    if extraction.status == config.STATUS_COMPLETED:
        render_extracted_content(extraction, "Extracted Content")
    else:
        if extraction.error:
            st.warning(extraction.error)
        if extraction.fallback_message:
            st.info(extraction.fallback_message)
        for note in extraction.notes:
            st.caption(note)


def render_extracted_content(extraction, heading: str) -> None:
    st.markdown(f"#### {heading}")
    if extraction.text:
        st.markdown("**Post text**")
        st.text(extraction.text)
    else:
        st.write("No post text was retrieved.")

    rows = [
        ("Title", extraction.title),
        ("Author / account", extraction.author),
        ("Author link", extraction.author_url),
        ("Site", extraction.site_name),
        ("Date as reported by the source", extraction.published),
    ]
    rows = [{"Field": k, "Value": v} for k, v in rows if v]
    if rows:
        st.table(rows)

    if extraction.media_urls:
        st.markdown("**Media references (not downloaded)**")
        st.table([{"Reference": url} for url in extraction.media_urls])
    elif not extraction.user_provided:
        st.caption("No media references were found.")

    for note in extraction.notes:
        st.caption(note)


def render_manual_fallback(expanded: bool) -> None:
    with st.expander("Provide the post text manually", expanded=expanded):
        with st.form("veriq_manual_form"):
            text = st.text_area(
                "Post text", max_chars=post_extractor.MAX_TEXT_CHARS, height=160
            )
            author = st.text_input("Author / account (optional)", max_chars=200)
            posted = st.text_input("Date or time shown on the post (optional)", max_chars=100)
            use_text = st.form_submit_button("Use this text")
        if use_text:
            st.session_state["veriq_manual"] = post_extractor.from_manual(text, author, posted)
        st.caption(
            "You can also switch to IMAGE INVESTIGATION and upload a screenshot or the "
            "post's image."
        )


# ------------------------------------------------------ Privacy/disclaimer
def render_privacy_panel() -> None:
    with st.expander("Privacy and data handling"):
        st.markdown(
            f"""
- **What is processed:** images you upload, analysed on this machine.
- **Where:** locally. Uploaded images are not sent to external services.
- **Post URL mode:** the URL you submit is requested from this machine. The
  site, and for X, YouTube and TikTok that platform's public oEmbed service,
  can see that request. Nothing from your uploaded images is sent. Text you
  paste manually stays on this machine.
- **Evidence search:** only when you click Search, the query text you can see
  is sent to Wikipedia and the GDELT news index. Recorded evidence and claims
  are kept for your current browser session only and are not written to disk.
- **What is stored:** only if "Remember this image's fingerprint" is ticked:
  hashes, the sanitised file name, dimensions and timestamps, in a local SQLite
  file. The image itself is never stored. Retrieved post content is kept only
  for your current browser session and is not written to disk. Other
  investigation records (findings, reports) are planned for later steps.
- **Temporary files:** removed after each analysis.
- **Advice:** avoid uploading highly sensitive or private material
  unless necessary.
- **Limit:** files up to {config.MAX_UPLOAD_MB} MB.
"""
        )
        try:
            stored = local_db.count_fingerprints()
            st.caption(f"Fingerprints currently stored locally: {stored}")
        except sqlite3.Error:
            st.caption("The local history could not be read.")
        if st.button("Clear local fingerprint history"):
            clear_local_history()


def render_disclaimer() -> None:
    st.markdown(f'<p class="muted">{config.DISCLAIMER}</p>', unsafe_allow_html=True)


# --------------------------------------------------------------------- Main
def main() -> None:
    render_header()
    render_tool_status()

    mode = st.radio(
        "Investigation mode",
        ["IMAGE INVESTIGATION", "POST URL INVESTIGATION"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.divider()

    if mode == "IMAGE INVESTIGATION":
        render_image_mode()
    else:
        render_url_mode()

    st.divider()
    render_privacy_panel()
    render_disclaimer()


main()