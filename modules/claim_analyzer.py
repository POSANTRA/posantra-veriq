"""POSANTRA | VERIQ - claim candidate extraction (Step 11).

Rule-based. It proposes sentences that look checkable (events, dates, figures,
places, attributions). It does NOT judge truth, and its place detection is a
rough capitalisation heuristic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

MAX_CLAIMS = 10
MIN_WORDS = 4
MAX_CLAIM_CHARS = 300

KIND_EVENT = "Event"
KIND_DATE = "Date"
KIND_RELATIVE = "Relative time"
KIND_NUMBER = "Figure"
KIND_PLACE = "Place"
KIND_ATTRIBUTION = "Attribution"

_URL = re.compile(r"https?://\S+", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
           r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DATE_PATTERNS = [
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}\b", re.I),
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\b", re.I),
]
_YEAR = re.compile(r"\b(?:in|since|during|from|of)\s+((?:19|20)\d{2})\b", re.I)
_RELATIVE = re.compile(
    r"\b(today|yesterday|tonight|this morning|this evening|last night|right now|"
    r"just now|this week|breaking)\b", re.I)
_EVENT = re.compile(
    r"\b(?:earthquake|quake|flood|fire|blast|explosion|attack|accident|crash|protest|"
    r"riot|arrest|kill|die|dead|death|injure|injury|collapse|cyclone|storm|landslide|"
    r"outbreak|announce|ban|launch|resign|win|elect|shoot)(?:s|es|ed|d|ing)?\b", re.I)
_ATTRIBUTION = re.compile(
    r"\b(?:according to|said|says|claims?|claimed|reported|reports|announced|confirmed|"
    r"officials?|minister|police)\b|[\"“”]", re.I)
_PLACE = re.compile(r"\b(?:in|at|near|from|across)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})")

_QUESTIONS = {
    KIND_EVENT: "Do official or reputable sources report this event, and do their time and place match?",
    KIND_DATE: "Does the date stated match when the event actually happened?",
    KIND_RELATIVE: "What date was this posted? Words like 'today' only make sense relative to the posting date.",
    KIND_NUMBER: "Do official or primary sources give the same figures?",
    KIND_PLACE: "Does the named place match where the event happened? (Depicted, publication and uploader locations are different things.)",
    KIND_ATTRIBUTION: "Can the attributed statement be found in the original source?",
}
GENERAL_QUESTIONS = [
    "Was any attached image or video published earlier, or in a different context?",
    "What is the earliest publicly discovered source for this content?",
]


@dataclass
class Claim:
    id: str = ""
    text: str = ""
    source_label: str = ""
    kinds: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    relative: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def find_dates(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _DATE_PATTERNS:
        found += [m.group(0).strip(" ,") for m in pattern.finditer(text)]
    found += [m.group(1) for m in _YEAR.finditer(text)]
    unique = list(dict.fromkeys(found))
    return [d for d in unique if not any(d != o and d in o for o in unique)]


def _analyse(sentence: str, label: str) -> Claim:
    claim = Claim(text=sentence, source_label=label)
    claim.dates = find_dates(sentence)
    claim.relative = list(dict.fromkeys(m.group(1).lower() for m in _RELATIVE.finditer(sentence)))
    claim.places = list(dict.fromkeys(m.group(1) for m in _PLACE.finditer(sentence)))

    rest = sentence
    for d in claim.dates:
        rest = rest.replace(d, " ")
    if _EVENT.search(sentence):
        claim.kinds.append(KIND_EVENT)
    if claim.dates:
        claim.kinds.append(KIND_DATE)
    if claim.relative:
        claim.kinds.append(KIND_RELATIVE)
    if re.search(r"\d", rest):
        claim.kinds.append(KIND_NUMBER)
    if claim.places:
        claim.kinds.append(KIND_PLACE)
    if _ATTRIBUTION.search(sentence):
        claim.kinds.append(KIND_ATTRIBUTION)
    claim.questions = [_QUESTIONS[k] for k in claim.kinds]
    return claim


def extract_claims(sources: list[tuple[str, str]]) -> list[Claim]:
    """Return up to MAX_CLAIMS candidate claims from (label, text) pairs."""
    claims: list[Claim] = []
    seen: set[str] = set()
    for label, text in sources:
        cleaned = _URL.sub(" ", text or "")
        for raw in _SPLIT.split(cleaned):
            sentence = re.sub(r"\s+", " ", raw).strip(" \t-•*")
            if not sentence or sentence.endswith("?"):
                continue
            words = [w for w in sentence.split() if not w.startswith(("#", "@"))]
            if len(words) < MIN_WORDS or sentence.lower() in seen:
                continue
            claim = _analyse(sentence[:MAX_CLAIM_CHARS], label)
            if not claim.kinds or claim.kinds == [KIND_PLACE]:
                continue
            seen.add(sentence.lower())
            claim.id = f"c{len(claims) + 1}"
            claims.append(claim)
            if len(claims) >= MAX_CLAIMS:
                return claims
    return claims


def parse_date(value: object) -> Optional[date]:
    s = str(value or "").strip()
    if not s:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if m:
        try:
            return date.fromisoformat(m.group(0))
        except ValueError:
            return None
    s = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", s).replace(",", "").strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def build_timeline(published: str, claims: list[Claim], evidence: list) -> list[dict]:
    """Collect dates as reported. Dated rows are sorted; undated-format rows follow."""
    rows: list[dict] = []
    if published:
        rows.append({"Date": published, "Event": "Post date as reported by the source",
                     "Source": "Source platform"})
    for claim in claims:
        for d in claim.dates:
            rows.append({"Date": d, "Event": f"Date mentioned in claim {claim.id}",
                         "Source": "Text under investigation"})
    for ev in evidence:
        if getattr(ev, "published", ""):
            rows.append({"Date": ev.published, "Event": f"Source published: {ev.source_title}",
                         "Source": ev.domain})
    dated = [(parse_date(r["Date"]), r) for r in rows]
    parsed = sorted((p for p in dated if p[0] is not None), key=lambda p: p[0])
    other = [p for p in dated if p[0] is None]
    return [r for _, r in parsed] + [r for _, r in other]