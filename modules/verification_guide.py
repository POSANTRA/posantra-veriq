"""POSANTRA | VERIQ - manual verification guide (Step 15).

Shown when an image has no provenance. Gives the user honest guidance and
checklists. It makes NO judgement about whether the image is AI-generated.
"""
from __future__ import annotations

import streamlit as st

REVERSE_SEARCH = [
    ("Google Lens", "https://lens.google.com/"),
    ("TinEye", "https://tineye.com/"),
    ("Bing Visual Search", "https://www.bing.com/visualsearch"),
    ("Yandex Images", "https://yandex.com/images/"),
]

ARTIFACT_CHECKLIST = [
    "Hands and fingers: wrong count, merged or oddly bent fingers.",
    "Text and signs: garbled, misspelled or meaningless lettering.",
    "Reflections, mirrors and glasses: do they match the scene?",
    "Shadows and lighting: do they all come from consistent directions?",
    "Backgrounds: warped lines, repeated patterns, objects melting together.",
    "Skin, hair and teeth: overly smooth, plastic-looking or inconsistent detail.",
    "Jewellery, straps and accessories: asymmetrical or fused to the body.",
    "Crowds and faces in the distance: distorted or duplicated faces.",
]
CAVEAT = ("Newer generators avoid many of these flaws, and real photos can show some "
          "of them. Finding or not finding artifacts proves nothing either way.")

NO_PROVENANCE_MESSAGE = (
    "This file carries no provenance. Screenshots and messaging apps (such as WhatsApp) "
    "create new files that drop the original's Content Credentials and metadata. "
    "VERIQ cannot tell whether this image was AI-generated or camera-made from the "
    "file alone."
)


def needs_guidance(meta) -> bool:
    """True when the file has no Content Credentials and no camera information."""
    if meta is None or getattr(meta, "status", None) != "Completed":
        return True
    has_cc = bool(getattr(meta, "content_credentials", None))
    found = getattr(meta, "found", {}) or {}
    return not has_cc and not (found.get("Camera make") or found.get("Camera model"))


def render_guide(meta) -> None:
    if not needs_guidance(meta):
        return
    st.markdown("#### How to Check Further")
    st.warning(NO_PROVENANCE_MESSAGE)
    st.markdown("**1. Reverse image search (the most useful step)**")
    st.caption("Look for an earlier copy that still has its credentials, or the post that "
               "first shared it. Download the image and upload it to one of these sites. "
               "VERIQ does not upload anything for you.")
    for name, url in REVERSE_SEARCH:
        st.markdown(f"- [{name}]({url})")
    st.markdown("**2. Visual artifact checklist**")
    for item in ARTIFACT_CHECKLIST:
        st.markdown(f"- {item}")
    st.caption(CAVEAT)
    st.markdown("**3. Ask for the original**")
    st.caption("Ask the sender for the original file (in WhatsApp, send it as a Document). "
               "Original files keep their metadata and credentials.")