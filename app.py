"""POSANTRA | VERIQ - Streamlit application shell (Step 3).

No analysis is performed here yet. This stage provides the layout,
mode selection, tool-status reporting and privacy/disclaimer text.
"""
from __future__ import annotations

import streamlit as st

import config

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
    ...rest unchanged...
</style>
"""


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
        rows.append(f"<div>{badge} &nbsp; <b>{label}</b> "
                    f"<span class='muted'>{detail}</span></div>")
    st.markdown(
        '<div class="veriq-panel"><h4>Analysis components</h4>'
        + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------ Mode: image
def render_image_mode() -> None:
    st.subheader("Image Investigation")
    st.write("Upload a JPG, JPEG, PNG or WebP image.")
    st.info("Image upload and analysis will be enabled in Step 4.")


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
    st.markdown(
        f'<p class="muted">{config.DISCLAIMER}</p>', unsafe_allow_html=True
    )


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