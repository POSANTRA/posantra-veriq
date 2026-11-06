"""POSANTRA | VERIQ - Streamlit application.

Step 7 state: image upload, validation, basic image information,
metadata analysis, OCR and basic forensic indicators. Hashing, verdicts
and URL investigation are added in later steps.
"""
from __future__ import annotations

import streamlit as st

import config
from modules import (
    forensic_analyzer,
    image_analyzer,
    metadata_analyzer,
    ocr_engine,
    security,
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
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


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

    render_media_information(data, validation, info)

    meta = metadata_analyzer.analyze_metadata(data, validation.extension)
    render_metadata(meta)

    with st.spinner("Running OCR..."):
        ocr = ocr_engine.extract_text(data)
    render_ocr(ocr)

    with st.spinner("Computing forensic indicators..."):
        forensics = forensic_analyzer.analyze_forensics(data)
    render_forensics(forensics)


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


# -------------------------------------------------------------- Mode: URL
def render_url_mode() -> None:
    st.subheader("Post URL Investigation")
    st.write("Enter a public social-media post URL.")
    st.info("URL investigation will be enabled in Step 10.")


# ------------------------------------------------------ Privacy/disclaimer
def render_privacy_panel() -> None:
    with st.expander("Privacy and data handling"):
        st.markdown(
            f"""
- **What is processed:** images you upload, analysed on this machine.
- **Where:** locally. Uploaded images are not sent to external services.
- **What is stored:** only investigation records (planned: hashes,
  extracted metadata, findings). Uploaded files are not kept permanently.
- **Temporary files:** removed after each analysis.
- **Advice:** avoid uploading highly sensitive or private material
  unless necessary.
- **Limit:** files up to {config.MAX_UPLOAD_MB} MB.
"""
        )


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