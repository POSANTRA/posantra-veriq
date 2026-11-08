"""POSANTRA | VERIQ - plain-language result (presentation logic only).

Never says an image is 'real'. Says 'made by AI' only when the file itself
declares it. For files that lost their information it can name the kind of file
(WhatsApp copy, screenshot), report a likely copy of an image seen before, or a
weak experimental pixel hint, always as a clue and never as proof.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from modules import metadata_analyzer as ma

GREEN, RED, AMBER, GREY = "#2ea36b", "#e5534b", "#d29922", "#8b949e"

ORIGIN_LABELS = {"ai": "AI label", "camera": "Camera details", "credentials": "Creation label"}

ON, ALERT, HINT, OFF, SKIP = "on", "alert", "hint", "off", "skip"


@dataclass
class SimpleResult:
    key: str
    icon: str
    headline: str
    sentence: str
    certainty: str
    colour: str
    bullets: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)
    clues: list = field(default_factory=list)


def _declares_ai(cc: dict) -> bool:
    return any("AI" in s for s in cc.get("digital_source_types", []))


def origin_of(meta) -> str:
    if meta is None or getattr(meta, "status", None) != config.STATUS_COMPLETED:
        return ""
    cc = getattr(meta, "content_credentials", None)
    if cc:
        return "ai" if _declares_ai(cc) else "credentials"
    found = getattr(meta, "found", None) or {}
    if found.get("Camera make") or found.get("Camera model"):
        return "camera"
    return ""


def _labelled_copy_match(comparison):
    if not comparison or not comparison.get("ok"):
        return None
    for match in comparison.get("matches") or []:
        if getattr(match, "origin", ""):
            return match
    return None


def summary_text(result: SimpleResult) -> str:
    lines = [f"VERIQ result: {result.headline} ({result.certainty})", result.sentence]
    if result.bullets:
        lines.append("")
        lines += [f"- {text}" for _, text in result.bullets]
    lines += ["", "VERIQ gives clues, not final proof."]
    return "\n".join(lines)


def _clues(cc, make, model, comparison, ocr, ai_hint, match, kind) -> list:
    out = []
    if kind is not None:
        known = getattr(kind, "key", "unknown") != "unknown"
        out.append((kind.icon, "Kind of file", ON if known else OFF,
                    kind.label if known else "Not clear"))
    if cc:
        out.append(("🔖", "Creation label", ALERT if _declares_ai(cc) else ON,
                    "Says AI made it" if _declares_ai(cc) else "Found, no AI mention"))
    else:
        out.append(("🔖", "Creation label", OFF, "None found"))
    out.append(("📷", "Camera details", ON if (make or model) else OFF,
                "Found (editable)" if (make or model) else "None found"))
    seen = bool(comparison and comparison.get("ok") and (comparison.get("exact") or match))
    out.append(("🧬", "Seen before", ON if seen else OFF, "Matches an earlier check" if seen else "No match"))
    has_text = bool(ocr is not None and getattr(ocr, "text", ""))
    out.append(("🔤", "Text in picture", ON if has_text else OFF, "Readable text found" if has_text else "No text read"))
    done = ai_hint is not None and getattr(ai_hint, "status", "") == config.STATUS_COMPLETED
    if not done:
        out.append(("🧪", "AI-pixel check", SKIP, "Not run"))
    elif ai_hint.level == "leans_ai":
        n = getattr(ai_hint, "votes_total", 0)
        out.append(("🧪", "AI-pixel check", HINT, f"All {n} models leaned AI (weak)" if n > 1 else "Leaned AI (weak)"))
    elif ai_hint.level == "no_signs":
        out.append(("🧪", "AI-pixel check", OFF, "No clear signs (proves nothing)"))
    else:
        out.append(("🧪", "AI-pixel check", OFF, "Undecided"))
    return out


def simplify(meta, ocr=None, comparison=None, ai_hint=None, kind=None) -> SimpleResult:
    usable = meta is not None and getattr(meta, "status", None) == config.STATUS_COMPLETED
    cc = getattr(meta, "content_credentials", None) if usable else None
    found = (getattr(meta, "found", None) or {}) if usable else {}
    make, model = found.get("Camera make"), found.get("Camera model")
    software = found.get(ma.SOFTWARE_LABEL, "")
    edited = bool(software) and any(n in software.lower() for n in ma._NOTABLE_SOFTWARE)
    match = _labelled_copy_match(comparison)
    clues = _clues(cc, make, model, comparison, ocr, ai_hint, match, kind)
    lost = bool(kind is not None and getattr(kind, "lost_info", False))

    bullets: list = []
    if lost:
        bullets.append((kind.icon, f"{kind.label}. {kind.sentence}"))
    if cc:
        if _declares_ai(cc):
            tool = cc.get("software_agent") or cc.get("generator") or "an AI tool"
            bullets.append(("🔖", f"The file's own hidden label says it was made with {tool}."))
        else:
            bullets.append(("🔖", "The file has a creation label, and it does not say AI made it."))
    if make or model:
        bullets.append(("📷", "Camera details are stored in the file. These can be edited, so they are a clue, not proof."))
    if edited:
        bullets.append(("✏️", f"It was saved by an editing app ({software[:60]})."))
    if not (cc or make or model or software):
        bullets.append(("🫥", "No hidden information was found. Screenshots, WhatsApp and social apps remove it."))
    if ocr is not None and getattr(ocr, "text", ""):
        bullets.append(("🔤", "There is readable text in the picture. Check whether what it says is true."))
    if comparison and comparison.get("ok") and comparison.get("exact"):
        bullets.append(("🗂️", "You have checked this exact file before."))

    search_steps = [
        "Search the picture on Google Lens or TinEye to find where it first appeared.",
        "Ask the sender for the original file (on WhatsApp, send it as a Document).",
        "Look closely at hands, text, shadows and backgrounds for odd mistakes.",
    ]

    if cc and _declares_ai(cc):
        return SimpleResult(
            "ai", "🤖", "Made by AI",
            "This image's own hidden label says an AI tool created it. That does not mean "
            "anyone meant to trick you. It only means this is not a real camera photo.",
            "The file itself says so", RED, bullets,
            ["Check how this image is being used. Is it presented as a real event?"], clues)
    if cc:
        return SimpleResult(
            "credentials", "🔖", "Has a creation label",
            "The file carries a creation label that does not mention AI. That is a useful "
            "clue, but VERIQ could not fully verify the label.",
            "Clue, not proof", AMBER, bullets, search_steps[:1], clues)
    if edited:
        return SimpleResult(
            "edited", "✏️", "Opened in an editing app",
            "The file was saved by editing software. Many normal photos are edited a little, "
            "so this alone does not mean the picture is fake.",
            "Clue, not proof", AMBER, bullets, search_steps, clues)
    if make or model:
        return SimpleResult(
            "camera", "📷", "Has camera details",
            "The file says it came from a camera. These details can be changed, so VERIQ "
            "cannot promise this is a real, untouched photo.",
            "Clue, not proof", AMBER, bullets, search_steps, clues)

    if match is not None:
        name = (match.filename or "an earlier image")[:60]
        seen = f"{name}, first checked {str(match.first_seen)[:10]}, match level: {match.level}"
        bullets.insert(0, ("🧬", f"Closely matches an image you checked before ({seen})."))
        if match.origin == "ai":
            return SimpleResult(
                "copy_ai", "🧬", "Looks like a copy of an AI image",
                "This picture closely matches an image you checked before, and that earlier "
                "file's own hidden label said an AI tool made it. This copy lost its label "
                "(screenshots and messaging apps do that), so this is a strong hint, not proof.",
                "Likely, not proof", RED, bullets,
                ["Confirm by searching the picture on Google Lens or TinEye.",
                 "Check how this copy is being presented to people."], clues)
        if match.origin == "camera":
            return SimpleResult(
                "copy_camera", "🧬", "Looks like a copy of a camera photo",
                "This picture closely matches an image you checked before, and that earlier "
                "file had camera details. Camera details can be edited, so this is only a "
                "clue about where it came from.",
                "Likely, not proof", AMBER, bullets, search_steps, clues)
        return SimpleResult(
            "copy_label", "🧬", "Looks like a copy of a labelled image",
            "This picture closely matches an image you checked before that carried a creation "
            "label. This copy lost it. It is a hint, not proof.",
            "Likely, not proof", AMBER, bullets, search_steps, clues)

    prefix = f"{kind.label}, so its hidden labels are likely gone. " if lost else ""
    hint_done = ai_hint is not None and getattr(ai_hint, "status", "") == config.STATUS_COMPLETED
    if hint_done and ai_hint.level == "no_signs":
        bullets.append(("🧪", "The experimental AI check saw no clear signs. This proves nothing: "
                              "it often misses AI images, especially screenshots."))
    elif hint_done and ai_hint.level == "unsure":
        bullets.append(("🧪", "The experimental AI check could not decide, or its models disagreed."))
    if hint_done and ai_hint.level == "leans_ai":
        n = getattr(ai_hint, "votes_total", 0)
        who = f"All {n} experimental AI models agreed" if n > 1 else f"An experimental AI check ({ai_hint.model})"
        bullets.insert(0, ("🧪", f"{who} leaned towards 'AI-made'. These checks are often wrong, "
                                 "especially on screenshots and WhatsApp copies."))
        return SimpleResult(
            "ai_hint", "🧪", "Might be AI-made (unsure)",
            prefix + "VERIQ checked the pixels with experimental models. They leaned towards AI, "
            "but this kind of check is often wrong and real photos can trigger it. Treat it as a "
            "reason to look further, not as an answer.",
            "Weak hint, models agree, often wrong" if n > 1 else "Weak hint, often wrong",
            AMBER, bullets, search_steps, clues)

    return SimpleResult(
        "unknown", "❓", "Can't tell",
        prefix + "This image has lost its hidden information, which is normal for screenshots and "
        "WhatsApp copies. From the file alone, nobody can honestly say whether it is AI-made "
        "or a real photo.",
        "Not enough to tell", GREY, bullets, search_steps, clues)