"""POSANTRA | VERIQ - public post retrieval (Step 10).

Reads only what a site publicly serves without login: the publisher's public
oEmbed endpoint (X, YouTube, TikTok) and the Open Graph link-preview tags.
It never logs in, spoofs a browser, retries around blocks or executes page
code. When retrieval fails it says so and offers the manual fallback.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

import config
from modules import url_validator as uv

FALLBACK_MESSAGE = (
    "Automatic retrieval was unavailable. You can provide the post text or "
    "upload a screenshot/image for investigation."
)
USER_AGENT = "POSANTRA-VERIQ/0.1 (link metadata reader; local investigation tool)"
MAX_REDIRECTS = 3
MAX_HTML_BYTES = 1_000_000
MAX_JSON_BYTES = 200_000
MAX_TEXT_CHARS = 5000
MAX_MEDIA = 10
BLOCKED_STATUSES = {401, 402, 403, 407, 429, 451}

OEMBED = {
    "x": "https://publish.twitter.com/oembed",
    "youtube": "https://www.youtube.com/oembed",
    "tiktok": "https://www.tiktok.com/oembed",
}

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LOGIN_PATH = re.compile(
    r"/(i/flow/login|login|signin|sign-in|accounts/login|checkpoint|uas/login)(/|$|\?)", re.I
)
_LOGIN_TITLE = re.compile(r"\b(log ?in|sign ?in)\b", re.I)

PREVIEW_NOTE = (
    "Page metadata is a link-preview summary. It may be truncated, incomplete, "
    "edited since posting, or removed."
)
DATE_NOTE = "Dates are as reported by the source and have not been independently verified."


@dataclass
class FetchResult:
    ok: bool
    status_code: int = 0
    final_url: str = ""
    content_type: str = ""
    body: bytes = b""
    truncated: bool = False
    error: Optional[str] = None


@dataclass
class PostExtraction:
    status: str
    method: str = ""
    error: Optional[str] = None
    text: str = ""
    title: str = ""
    author: str = ""
    author_url: str = ""
    site_name: str = ""
    published: str = ""
    media_urls: list[str] = field(default_factory=list)
    final_url: str = ""
    attempts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fallback_message: Optional[str] = None
    user_provided: bool = False


# ------------------------------------------------------------------ helpers
def _clean(value: object, limit: int) -> str:
    text = _CTRL.sub("", str(value or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def _http_urls(values: list[str]) -> list[str]:
    """Keep only plain http(s) URLs; drop javascript:, data: and anything else."""
    out: list[str] = []
    for value in values:
        url = _clean(value, 2048)
        if url.lower().startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out[:MAX_MEDIA]


# ------------------------------------------------------------------- fetch
def _safe_get(url: str, accept: str, max_bytes: int) -> FetchResult:
    """GET with SSRF checks on every hop, manual redirects, timeout and size cap."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        info = uv.parse_url(current)
        if not info.ok:
            return FetchResult(False, error="Blocked unsafe or invalid address: " + info.errors[0])
        problem = uv.check_public_host(info.host)
        if problem:
            return FetchResult(False, error=problem)

        try:
            resp = requests.get(
                info.normalized,
                headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en"},
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            )
        except requests.Timeout:
            return FetchResult(False, error="The request timed out.")
        except requests.RequestException as exc:
            return FetchResult(False, error=f"The request failed ({type(exc).__name__}).")

        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    return FetchResult(False, status_code=resp.status_code,
                                       error="A redirect had no destination.")
                current = urljoin(info.normalized, location)
                continue

            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            body = bytearray()
            truncated = False
            for chunk in resp.iter_content(chunk_size=16384):
                body.extend(chunk)
                if len(body) > max_bytes:
                    del body[max_bytes:]
                    truncated = True
                    break
            return FetchResult(True, resp.status_code, info.normalized,
                               content_type, bytes(body), truncated)
        except requests.RequestException as exc:
            return FetchResult(False, error=f"The response could not be read ({type(exc).__name__}).")
        finally:
            resp.close()
    return FetchResult(False, error="Too many redirects.")


def _describe_failure(source: str, fetched: FetchResult) -> str:
    if not fetched.ok:
        return f"{source}: {fetched.error}"
    if fetched.status_code in BLOCKED_STATUSES:
        return (f"{source}: access was refused (HTTP {fetched.status_code}). "
                "VERIQ does not log in or bypass access controls.")
    if fetched.status_code in (404, 410):
        return f"{source}: the post was not found (HTTP {fetched.status_code}); it may be deleted or private."
    return f"{source}: unexpected response (HTTP {fetched.status_code})."


# ------------------------------------------------------------------- oEmbed
def _try_oembed(info: uv.UrlInfo, attempts: list[str]) -> Optional[PostExtraction]:
    params = {"url": info.normalized, "format": "json"}
    if info.platform_key == "x":
        params["omit_script"] = "1"
    fetched = _safe_get(f"{OEMBED[info.platform_key]}?{urlencode(params)}",
                        "application/json", MAX_JSON_BYTES)
    source = f"{info.platform_name} public oEmbed"
    if not fetched.ok or fetched.status_code != 200:
        attempts.append(_describe_failure(source, fetched))
        return None
    try:
        data = json.loads(fetched.body.decode("utf-8", errors="replace"))
    except ValueError:
        attempts.append(f"{source}: the response could not be read.")
        return None
    if not isinstance(data, dict):
        attempts.append(f"{source}: the response had an unexpected shape.")
        return None

    result = PostExtraction(
        status=config.STATUS_COMPLETED,
        method=f"{info.platform_name} public oEmbed",
        author=_clean(data.get("author_name"), 200),
        author_url=_clean(data.get("author_url"), 500),
        site_name=_clean(data.get("provider_name") or info.platform_name, 100),
        final_url=info.normalized,
    )
    if info.platform_key == "x":
        soup = BeautifulSoup(str(data.get("html") or ""), "html.parser")
        paragraph = soup.find("p")
        result.text = _clean(paragraph.get_text("\n") if paragraph else "", MAX_TEXT_CHARS)
        links = soup.find_all("a")
        result.published = _clean(links[-1].get_text() if links else "", 100)
        result.notes.append(
            "oEmbed returns the post text only. Attached images and videos, and any "
            "text inside them, are not included."
        )
    else:
        result.title = _clean(data.get("title"), 500)
        result.text = result.title
        result.media_urls = _http_urls([str(data.get("thumbnail_url") or "")])
        result.notes.append(
            "Only the public title or caption was retrieved. The video content itself "
            "has not been analysed."
        )
    result.notes.append(DATE_NOTE)

    if not (result.text or result.title):
        attempts.append(f"{source}: no post content was returned.")
        return None
    attempts.append(f"{source}: content retrieved.")
    return result


# ------------------------------------------------------ Open Graph metadata
def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = (soup.find("meta", attrs={"property": name})
               or soup.find("meta", attrs={"name": name}))
        if tag and tag.get("content"):
            return _clean(tag["content"], 2000)
    return ""


def _try_generic(info: uv.UrlInfo, attempts: list[str]) -> Optional[PostExtraction]:
    source = "Page metadata (Open Graph)"
    fetched = _safe_get(info.normalized, "text/html,application/xhtml+xml", MAX_HTML_BYTES)
    if not fetched.ok or fetched.status_code != 200:
        attempts.append(_describe_failure(source, fetched))
        return None
    if fetched.content_type and not fetched.content_type.startswith(("text/html", "application/xhtml")):
        attempts.append(f"{source}: the response was not a web page ({fetched.content_type}).")
        return None

    soup = BeautifulSoup(fetched.body.decode("utf-8", errors="replace"), "html.parser")
    title = _meta(soup, "og:title", "twitter:title") or _clean(
        soup.title.get_text() if soup.title else "", 500)
    description = _meta(soup, "og:description", "twitter:description", "description")

    if _LOGIN_PATH.search(fetched.final_url) or (_LOGIN_TITLE.search(title) and not description):
        attempts.append(
            f"{source}: a login page was returned instead of the post. "
            "VERIQ does not log in or bypass access controls."
        )
        return None
    if not (title or description):
        attempts.append(f"{source}: the page exposed no readable preview information.")
        return None

    result = PostExtraction(
        status=config.STATUS_COMPLETED,
        method=source,
        text=_clean(description, MAX_TEXT_CHARS),
        title=_clean(title, 500),
        author=_meta(soup, "article:author", "author", "twitter:creator")[:200],
        site_name=_meta(soup, "og:site_name")[:100] or info.platform_name,
        published=_meta(soup, "article:published_time", "og:article:published_time")[:100],
        media_urls=_http_urls([_meta(soup, "og:image", "twitter:image"),
                               _meta(soup, "og:video", "og:video:url")]),
        final_url=fetched.final_url,
    )
    result.notes.append(PREVIEW_NOTE)
    if result.published:
        result.notes.append(DATE_NOTE)
    if fetched.truncated:
        result.notes.append("The page was larger than the size limit, so only its start was read.")
    attempts.append(f"{source}: content retrieved.")
    return result


# ------------------------------------------------------------------- entry
def extract(info: uv.UrlInfo) -> PostExtraction:
    """Attempt permitted retrieval. Never raises; always returns a usable result."""
    if not info.ok:
        return PostExtraction(
            status=config.STATUS_FAILED,
            error=" ".join(info.errors) or "The URL was not accepted.",
            fallback_message=FALLBACK_MESSAGE,
        )
    attempts: list[str] = []
    try:
        result = None
        if info.platform_key in OEMBED:
            result = _try_oembed(info, attempts)
        if result is None:
            result = _try_generic(info, attempts)
    except Exception as exc:  # hostile content must never crash the app
        return PostExtraction(
            status=config.STATUS_FAILED,
            error=f"Retrieval failed unexpectedly ({type(exc).__name__}).",
            attempts=attempts,
            fallback_message=FALLBACK_MESSAGE,
        )

    if result is None:
        notes = []
        if info.platform_key in ("facebook", "instagram", "linkedin", "threads"):
            notes.append(f"{info.platform_name} commonly requires login to view posts, "
                         "so automatic retrieval often fails.")
        return PostExtraction(
            status=config.STATUS_MANUAL,
            error="No public content could be retrieved.",
            attempts=attempts,
            notes=notes,
            fallback_message=FALLBACK_MESSAGE,
        )
    result.attempts = attempts
    return result


def from_manual(text: str, author: str = "", published: str = "") -> PostExtraction:
    """Wrap text typed or pasted by the user. Its provenance is the user, not the platform."""
    cleaned = _clean(text, MAX_TEXT_CHARS)
    if not cleaned:
        return PostExtraction(status=config.STATUS_FAILED, method="Provided by user",
                              error="No text was provided.", user_provided=True)
    return PostExtraction(
        status=config.STATUS_COMPLETED,
        method="Provided by user",
        text=cleaned,
        author=_clean(author, 200),
        published=_clean(published, 100),
        user_provided=True,
        notes=["This text was supplied by you. VERIQ cannot confirm that it matches the original post."],
    )