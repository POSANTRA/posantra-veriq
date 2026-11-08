"""POSANTRA | VERIQ - plain-language result for post links (presentation only).

Never says a post is 'true' or 'fake'. Only reports what was read, what looks
checkable, and (if a person recorded evidence) the evidence-based outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from modules import verdict_engine as ve

GREEN, RED, AMBER, GREY = "#2ea36b", "#e5534b", "#d29922", "#8b949e"

MEDIA_PLATFORMS = ("instagram", "facebook", "tiktok", "threads", "x", "youtube")

_EVIDENCE_WORDS = {
    ve.AUTHENTIC: ("✅", "Sources back this up", GREEN,
                   "Reliable sources you recorded support what the post says. This is about "
                   "the words, not about any photo or video attached."),
    ve.CONTRADICTED: ("🚫", "Sources say this is wrong", RED,
                      "Reliable sources you recorded contradict what the post says."),
    ve.MISLEADING_CONTEXT: ("⚠️", "Possibly misleading", AMBER,
                            "The picture or claim seems to come from an earlier or different "
                            "situation than the one the post presents."),
    ve.UNVERIFIED: ("❓", "Still unconfirmed", AMBER,
                    "The evidence recorded so far is not enough to confirm or reject this post."),
}


@dataclass
class SimplePost:
    key: str
    icon: str
    headline: str
    sentence: str
    certainty: str
    colour: str
    bullets: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)
    claims: list = field(default_factory=list)


def simplify_post(info, extraction, manual, claim_result=None, image_checked: bool = False) -> SimplePost:
    manual_ok = manual is not None and manual.status == config.STATUS_COMPLETED
    extraction_ok = extraction is not None and extraction.status == config.STATUS_COMPLETED
    text_ok = extraction_ok or manual_ok

    if info is not None and not info.ok and not manual_ok:
        return SimplePost(
            "invalid", "⚠️", "Link not accepted",
            "This link could not be used. It may be mistyped, or it points somewhere VERIQ "
            "will not contact for safety.",
            "Nothing was checked", AMBER,
            [("🔗", m) for m in info.errors[:3]],
            ["Copy the full link from the post and try again.",
             "Or use the box below to paste the post's text."])

    if not text_ok:
        return SimplePost(
            "blocked", "🔒", "Couldn't open this post",
            "The site did not give out the post's text. Many platforms require a login, and "
            "VERIQ never logs in or works around blocks.",
            "Not enough to tell", GREY,
            [("🫥", "No public text was available.")],
            ["Copy the post's text and paste it in the box below.",
             "Or take a screenshot and use Check an Image."])

    bullets: list = []
    if extraction_ok:
        who = extraction.author or extraction.site_name
        bullets.append(("📄", "Read the post's public text" + (f" ({who[:60]})." if who else ".")))
        if extraction.published:
            bullets.append(("🗓️", f"The platform shows the date: {extraction.published[:60]}. "
                                  "VERIQ has not verified it."))
        if extraction.media_urls and not image_checked:
            bullets.append(("🖼️", "The post has a picture or video. VERIQ did not check it. "
                                  "Download it and use Check an Image."))
    if manual_ok:
        bullets.append(("✍️", "You supplied some of the text, so VERIQ cannot confirm it matches the post."))

    claims = (claim_result or {}).get("claims") or []
    verdict = (claim_result or {}).get("verdict")
    evidence = (claim_result or {}).get("evidence") or []
    assessed = bool(verdict is not None and getattr(verdict, "context_checked", False))

    if assessed and verdict.assessment in _EVIDENCE_WORDS:
        icon, head, colour, sentence = _EVIDENCE_WORDS[verdict.assessment]
        bullets.append(("📚", f"{len(evidence)} source(s) recorded. Strength: {verdict.strength}."))
        return SimplePost("evidence", icon, head, sentence, verdict.strength, colour,
                          bullets, ["Open the technical report to see each source and why it matters."],
                          claims)

    if claims:
        bullets.append(("🔎", f"Found {len(claims)} statement(s) that can be fact-checked."))
        return SimplePost(
            "claims", "🔎", "Claims found, not checked yet",
            "VERIQ read the post and found statements that can be fact-checked, but it has not "
            "compared them with reliable sources yet. It cannot tell you if they are true.",
            "Not checked yet", AMBER, bullets,
            ["Turn on the technical report below, search public sources and record what they say.",
             "Or search the main claim on a trusted news site or fact-checker yourself."],
            claims)

    # No checkable statements found.
    media_note = (not image_checked) and (bool(extraction_ok and extraction.media_urls) or (
        info is not None and getattr(info, "platform_key", "") in MEDIA_PLATFORMS))
    if media_note:
        bullets.append(("🖼️", "This kind of post is mostly about a picture or video. VERIQ read "
                              "only the text and did NOT examine the picture or video."))
        return SimplePost(
            "nothing", "📝", "No checkable text found",
            "The text has no clear facts to check, and VERIQ did not look at any picture or "
            "video in the post. That does not mean the post is real, safe or true.",
            "Picture not examined", GREY, bullets,
            ["To check the picture: save it or take a screenshot, then use Check an Image.",
             "Search the picture on Google Lens or TinEye to find where it first appeared."],
            claims)
    return SimplePost(
        "nothing", "📝", "Nothing to fact-check",
        "The text reads like opinion, a joke or a greeting, with no clear facts to check. "
        "That does not make it harmless or true.",
        "Nothing checkable found", GREY, bullets,
        ["If something in it worries you, check the sender and the source."], claims)