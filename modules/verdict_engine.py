"""POSANTRA | VERIQ - investigation and verdict engine (Step 9).

Combines the evidence gathered by the other modules into one of six fixed
assessments, an evidence-strength label and a written reason.

For a lone image with no claim attached, the engine cannot reach AUTHENTIC,
MISLEADING CONTEXT or CONTRADICTED: those require a claim and outside
evidence (Steps 10 and 11). No numeric probabilities are produced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import config
from modules import metadata_analyzer as ma

# ------------------------------------------------------------ fixed vocabulary
AUTHENTIC = "AUTHENTIC"
MANIPULATED = "MANIPULATED"
MISLEADING_CONTEXT = "MISLEADING CONTEXT"
UNVERIFIED = "UNVERIFIED"
CONTRADICTED = "CONTRADICTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT EVIDENCE"

ASSESSMENTS = (
    AUTHENTIC, MANIPULATED, MISLEADING_CONTEXT,
    UNVERIFIED, CONTRADICTED, INSUFFICIENT_EVIDENCE,
)

STRENGTH_HIGH = "High evidentiary support"
STRENGTH_MODERATE = "Moderate evidentiary support"
STRENGTH_LIMITED = "Limited evidentiary support"
STRENGTH_INSUFFICIENT = "Insufficient evidence"

# Finding weights
INDICATES = "Indicates"        # evidence pointing toward an assessment
OBSERVATION = "Observation"    # worth a human look, decides nothing
INFO = "Information"           # context only

_TEXT_LIMIT = 100

BASE_LIMITATIONS = [
    "No claim or surrounding context was investigated. Researching claims "
    "against public sources is not yet part of image analysis in this version.",
    "Missing metadata is normal and does not indicate manipulation. Screenshots, "
    "messaging apps and social platforms routinely remove it.",
    "Embedded metadata can be edited, stripped or fabricated.",
    "Forensic indicators are not proof, and an image without indicators is not "
    "thereby shown to be authentic.",
    "Fingerprint comparison covers only images analysed by this installation. It is "
    "not a reverse image search, so it says nothing about where else an image appears.",
]


@dataclass
class Finding:
    area: str
    text: str
    weight: str


@dataclass
class Verdict:
    assessment: str
    strength: str
    reason: str
    findings: list[Finding] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    suggested_checks: list[str] = field(default_factory=list)
    incomplete_components: list[str] = field(default_factory=list)
    context_checked: bool = False


# ------------------------------------------------------------------- helpers
def _clip(value: object) -> str:
    text = str(value).strip()
    return text if len(text) <= _TEXT_LIMIT else text[:_TEXT_LIMIT] + "…"


def _unusable(component: object) -> bool:
    """True if a component is missing or did not produce results."""
    status = getattr(component, "status", None)
    return component is None or status in (config.STATUS_FAILED, config.STATUS_NOT_AVAILABLE)


def _declares_ai(credentials: dict) -> bool:
    return any("AI-generated" in s for s in credentials.get("digital_source_types", []))


# ------------------------------------------------------------------ evaluate
def evaluate(meta, ocr, forensics, hashes, comparison: Optional[dict] = None) -> Verdict:
    """Produce an assessment from analysis results. Never raises on missing parts."""
    findings: list[Finding] = []
    incomplete: list[str] = []
    limitations = list(BASE_LIMITATIONS)
    checks = [
        "Run a manual reverse image search (for example Google Lens or TinEye) to "
        "look for earlier or other appearances of this image.",
    ]
    ai_declared = False
    ai_agent = ""
    has_signal = False

    # --- metadata and provenance
    if _unusable(meta):
        incomplete.append("Metadata")
    else:
        cc = meta.content_credentials
        if cc:
            has_signal = True
            if _declares_ai(cc):
                ai_declared = True
                ai_agent = _clip(cc.get("software_agent") or cc.get("generator") or "an unnamed tool")
                findings.append(Finding(
                    "Provenance",
                    f"Embedded Content Credentials declare AI-generated content (tool: {ai_agent}).",
                    INDICATES))
            else:
                findings.append(Finding(
                    "Provenance",
                    "Embedded Content Credentials (C2PA) are present and do not declare "
                    "AI generation.",
                    OBSERVATION))
            limitations.append(
                "Content Credentials were read but their signature was not "
                "cryptographically validated, so a forged or altered manifest would "
                "look the same to VERIQ.")

        make = meta.found.get("Camera make")
        model = meta.found.get("Camera model")
        if make or model:
            has_signal = True
            findings.append(Finding(
                "Metadata",
                f"Camera make/model recorded: {_clip(' '.join(x for x in (make, model) if x))}. "
                "This is self-reported and editable.",
                INFO))
        for label in ("Date/time original", "Date/time created"):
            if label in meta.found:
                has_signal = True
                findings.append(Finding(
                    "Metadata", f"{label} recorded: {_clip(meta.found[label])}. Editable and unverified.", INFO))
                break

        software = meta.found.get(ma.SOFTWARE_LABEL)
        if software:
            has_signal = True
            notable = any(name in software.lower() for name in ma._NOTABLE_SOFTWARE)
            if notable:
                findings.append(Finding(
                    "Metadata",
                    f"Software field names '{_clip(software)}', associated with image editing or "
                    "generation. It shows the file passed through that software, not that the "
                    "content was misleadingly altered.",
                    OBSERVATION))
            else:
                findings.append(Finding("Metadata", f"Software field: {_clip(software)}.", INFO))

        if meta.gps:
            has_signal = True
            findings.append(Finding(
                "Metadata",
                "Embedded GPS coordinates are present. They are file metadata, may be altered, "
                "and do not show where the uploader is.",
                INFO))
            checks.append("Treat the embedded GPS coordinates as a lead and check them "
                          "against independent evidence about the depicted place.")

        if meta.found and not (make or model) and not software and not cc:
            has_signal = True

    # --- forensic indicators
    if _unusable(forensics):
        incomplete.append("Forensic indicators")
    else:
        for ind in forensics.indicators:
            if ind.status == config.STATUS_COMPLETED and ind.significance == "observation":
                has_signal = True
                findings.append(Finding("Forensic", f"{ind.name}: {_clip(ind.summary)}", OBSERVATION))

    # --- OCR
    if _unusable(ocr):
        incomplete.append("OCR")
    elif ocr.text:
        has_signal = True
        findings.append(Finding(
            "Text",
            f"{ocr.word_count} word(s) of text were extracted from the image. OCR can contain "
            "errors, and any factual claims in it have not yet been researched.",
            INFO))
        checks.append("Read the extracted text and check any factual claims in it against "
                      "reliable public sources.")

    # --- fingerprints and local history (information only, never a signal)
    if _unusable(hashes):
        incomplete.append("Fingerprints")
    elif comparison and comparison.get("ok"):
        if comparison.get("exact"):
            findings.append(Finding(
                "History",
                "A byte-identical file was analysed before by this installation. This says "
                "nothing about the file's origin.",
                INFO))
        if comparison.get("matches"):
            findings.append(Finding(
                "History",
                f"{len(comparison['matches'])} visually similar image(s) exist in this "
                "installation's history. Similar images may be copies or unrelated look-alikes.",
                INFO))

    # --- decision
    if ai_declared:
        assessment, strength = MANIPULATED, STRENGTH_MODERATE
        reason = (
            f"The file's own embedded Content Credentials declare that its content was "
            f"AI-generated (tool: {ai_agent}). This is a self-declared provenance record and "
            "VERIQ has not validated its signature. In VERIQ's six categories this is "
            "reported as MANIPULATED because the image is not an unaltered capture of a real "
            "scene. It does not show intent to deceive, and it says nothing about any claim "
            "attached to the image."
        )
    elif has_signal:
        assessment, strength = UNVERIFIED, STRENGTH_LIMITED
        reason = (
            "VERIQ found some technical signals, listed below, but none of them confirms or "
            "contradicts the image, and no claim or context was investigated. Embedded data "
            "can be edited or stripped, and forensic indicators are not proof. There is not "
            "enough reliable evidence to confirm or reject this image."
        )
    else:
        assessment, strength = INSUFFICIENT_EVIDENCE, STRENGTH_INSUFFICIENT
        reason = (
            "The image carries no embedded provenance, no readable text and no notable "
            "technical indicators, and no claim was investigated. That leaves too little "
            "material for a meaningful investigation. This is not a finding about "
            "authenticity in either direction."
        )

    if incomplete:
        reason += " Some analysis components did not complete: " + ", ".join(incomplete) + "."

    return Verdict(
        assessment=assessment,
        strength=strength,
        reason=reason,
        findings=findings,
        limitations=limitations,
        suggested_checks=checks,
        incomplete_components=incomplete,
        context_checked=False,
    )