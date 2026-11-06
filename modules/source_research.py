"""POSANTRA | VERIQ - evidence model and free public search (Step 11).

Search results are NOT judged automatically. Stance and explanation are
recorded by the user. Source tiers come from the web domain (a starting
list, not an endorsement) or are set by the user; unknown domains stay
"Unclassified". Result links are never fetched by VERIQ.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from typing import Optional
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup

from modules import post_extractor as pe
from modules import url_validator as uv

SUPPORTS = "Supports"
CONTRADICTS = "Contradicts"
NEUTRAL = "Neutral"
NOT_ASSESSED = "Not yet assessed"
STANCES = (SUPPORTS, CONTRADICTS, NEUTRAL, NOT_ASSESSED)

TYPE_REPORT = "Direct report"
TYPE_OFFICIAL = "Official statement"
TYPE_FACTCHECK = "Fact-check"
TYPE_EARLIER = "Earlier publication of the media"
TYPE_BACKGROUND = "Background / context"
TYPE_OTHER = "Other"
EVIDENCE_TYPES = (TYPE_REPORT, TYPE_OFFICIAL, TYPE_FACTCHECK, TYPE_EARLIER,
                  TYPE_BACKGROUND, TYPE_OTHER)

TIERS = {
    1: "Official government source",
    2: "Official organisation",
    3: "Primary document",
    4: "Reputable news organisation",
    5: "Academic / research source",
    6: "Established fact-checking organisation",
    7: "Secondary source",
    8: "Social media post",
    9: "Anonymous / unverified source",
    0: "Unclassified",
}
RELIABLE_MAX_TIER = 6

# Starting lists. Edit them to suit your needs. Inclusion is not an endorsement.
_GOV = ("gov", "gov.in", "nic.in", "gov.uk", "gov.au", "mil", "gc.ca", "gov.sg")
_ORG = ("un.org", "int", "worldbank.org", "imf.org", "icrc.org", "redcross.org",
        "oecd.org", "europa.eu")
_FACTCHECK = ("snopes.com", "factcheck.org", "politifact.com", "boomlive.in", "altnews.in",
              "factly.in", "vishvasnews.com", "fullfact.org", "factcheck.afp.com",
              "leadstories.com", "newschecker.in")
_NEWS = ("reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "thehindu.com",
         "indianexpress.com", "hindustantimes.com", "ndtv.com", "ptinews.com",
         "theguardian.com", "nytimes.com", "washingtonpost.com", "aljazeera.com",
         "dw.com", "npr.org", "pbs.org", "thewire.in", "scroll.in", "livemint.com",
         "business-standard.com", "timesofindia.indiatimes.com")
_ACADEMIC = ("edu", "ac.in", "edu.in", "ac.uk", "edu.au", "nature.com", "science.org",
             "thelancet.com", "arxiv.org")
_SECONDARY = ("wikipedia.org",)

MAX_QUERY_CHARS = 200
MAX_JSON_BYTES = 400_000
GDELT_MIN_INTERVAL = 5.0
_last_gdelt: Optional[float] = None


@dataclass
class Evidence:
    source_title: str = ""
    url: str = ""
    domain: str = ""
    published: str = ""
    retrieved: str = ""
    evidence_type: str = TYPE_OTHER
    relevance: str = ""          # which claim this relates to
    stance: str = NOT_ASSESSED
    explanation: str = ""
    tier: int = 0
    provider: str = ""
    added_by: str = "user"

    @property
    def tier_label(self) -> str:
        return TIERS.get(self.tier, TIERS[0])


@dataclass
class SearchResult:
    title: str
    url: str
    domain: str
    published: str
    snippet: str
    provider: str
    tier: int

    @property
    def tier_label(self) -> str:
        return TIERS.get(self.tier, TIERS[0])


# ------------------------------------------------------------------ helpers
def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _matches(host: str, suffixes: tuple) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def classify_domain(host: str) -> int:
    host = (host or "").lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return 0
    if uv.detect_platform(host)[0]:
        return 8
    for tier, suffixes in ((1, _GOV), (2, _ORG), (6, _FACTCHECK), (4, _NEWS),
                           (5, _ACADEMIC), (7, _SECONDARY)):
        if _matches(host, suffixes):
            return tier
    return 0


def sanitize_query(query: object) -> str:
    q = re.sub(r"[^\w\s\-'.,]", " ", str(query or ""), flags=re.UNICODE)
    return re.sub(r"\s+", " ", q).strip()[:MAX_QUERY_CHARS]


def default_query(text: str, words: int = 12) -> str:
    return sanitize_query(" ".join(str(text or "").split()[:words]))


def _fetch_json(url: str):
    fetched = pe._safe_get(url, "application/json", MAX_JSON_BYTES)
    if not fetched.ok:
        return None, fetched.error
    if fetched.status_code != 200:
        return None, f"unexpected response (HTTP {fetched.status_code})"
    try:
        return json.loads(fetched.body.decode("utf-8", errors="replace")), None
    except ValueError:
        return None, "the service returned a response that was not readable data (it may be rate-limiting)"


def _accept_url(url: str):
    info = uv.parse_url(url)
    return info if info.ok else None


# ------------------------------------------------------------------ searches
def wikipedia_search(query: str) -> tuple[list[SearchResult], Optional[str]]:
    q = sanitize_query(query)
    if len(q) < 3:
        return [], "Wikipedia: the query is too short."
    url = "https://en.wikipedia.org/w/api.php?" + urlencode(
        {"action": "query", "list": "search", "srsearch": q, "srlimit": 5,
         "format": "json", "utf8": 1})
    data, error = _fetch_json(url)
    if error:
        return [], f"Wikipedia: {error}"
    try:
        items = data["query"]["search"]
    except (TypeError, KeyError):
        return [], "Wikipedia: the response had an unexpected shape."
    results: list[SearchResult] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = _clean(item["title"], 200)
        link = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_()")
        snippet = BeautifulSoup(str(item.get("snippet") or ""), "html.parser").get_text()
        stamp = _clean(item.get("timestamp"), 30)
        results.append(SearchResult(
            title, link, "en.wikipedia.org", "",
            _clean(snippet, 300) + (f" (page last edited {stamp[:10]})" if stamp else ""),
            "Wikipedia", 7))
    return results, None


def gdelt_search(query: str) -> tuple[list[SearchResult], Optional[str]]:
    global _last_gdelt
    q = sanitize_query(query)
    if len(q) < 3:
        return [], "GDELT: the query is too short."
    if _last_gdelt is not None:
        wait = GDELT_MIN_INTERVAL - (time.monotonic() - _last_gdelt)
        if wait > 0:
            return [], f"GDELT: it allows about one request every 5 seconds. Wait {ceil(wait)} s and search again."
    _last_gdelt = time.monotonic()
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(
        {"query": q, "mode": "artlist", "maxrecords": 10, "format": "json", "sort": "datedesc"})
    data, error = _fetch_json(url)
    if error:
        return [], f"GDELT: {error}"
    articles = data.get("articles") if isinstance(data, dict) else None
    results: list[SearchResult] = []
    for item in articles if isinstance(articles, list) else []:
        if not isinstance(item, dict):
            continue
        info = _accept_url(str(item.get("url") or ""))
        if info is None:
            continue
        seen = str(item.get("seendate") or "")
        published = f"{seen[0:4]}-{seen[4:6]}-{seen[6:8]}" if re.match(r"\d{8}T", seen) else ""
        results.append(SearchResult(
            _clean(item.get("title") or info.host, 200), info.normalized, info.host,
            published, "Date is when GDELT first saw the article, not necessarily its publication date.",
            "GDELT news index", classify_domain(info.host)))
    return results, None


def search_all(query: str) -> tuple[list[SearchResult], list[str]]:
    results: list[SearchResult] = []
    errors: list[str] = []
    for search in (wikipedia_search, gdelt_search):
        found, error = search(query)
        results += found
        if error:
            errors.append(error)
    return results, errors


# ------------------------------------------------------------ evidence build
def evidence_from_result(result: SearchResult, stance: str, evidence_type: str,
                         explanation: str, claim_id: str) -> tuple[Optional[Evidence], Optional[str]]:
    if stance not in STANCES:
        return None, "Unknown stance."
    explanation = _clean(explanation, 1000)
    if stance != NOT_ASSESSED and not explanation:
        return None, f"'{result.title[:60]}': explain why this source supports, contradicts or is neutral."
    return Evidence(
        source_title=result.title, url=result.url, domain=result.domain,
        published=result.published, retrieved=_today(),
        evidence_type=evidence_type if evidence_type in EVIDENCE_TYPES else TYPE_OTHER,
        relevance=claim_id, stance=stance, explanation=explanation,
        tier=result.tier, provider=result.provider, added_by="search result"), None


def make_manual_evidence(title: str, url: str, published: str, evidence_type: str,
                         stance: str, explanation: str, claim_id: str,
                         tier_override: Optional[int] = None) -> tuple[Optional[Evidence], Optional[str]]:
    info = uv.parse_url(url)
    if not info.ok:
        return None, "The source URL was not accepted: " + " ".join(info.errors)
    title = _clean(title, 200)
    if not title:
        return None, "Enter a source title."
    if stance not in STANCES:
        return None, "Unknown stance."
    explanation = _clean(explanation, 1000)
    if stance != NOT_ASSESSED and not explanation:
        return None, "Explain why this source supports, contradicts or is neutral."
    tier = tier_override if tier_override in TIERS else classify_domain(info.host)
    return Evidence(
        source_title=title, url=info.normalized, domain=info.host,
        published=_clean(published, 100), retrieved=_today(),
        evidence_type=evidence_type if evidence_type in EVIDENCE_TYPES else TYPE_OTHER,
        relevance=claim_id, stance=stance, explanation=explanation,
        tier=tier, provider="Entered by user", added_by="user"), None


def add_unique(items: list[Evidence], new: Evidence) -> bool:
    if any(e.url == new.url and e.relevance == new.relevance for e in items):
        return False
    items.append(new)
    return True