"""POSANTRA | VERIQ - URL validation and SSRF guard (Step 10).

Treats every submitted URL as hostile. Parsing is strict, and hostnames must
resolve only to public addresses before anything is requested.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
ALLOWED_PORTS = {None, 80, 443}
_BAD_CHARS = re.compile(r"[\x00-\x20\x7f]")
_BLOCKED_SUFFIXES = (
    ".local", ".localhost", ".internal", ".lan", ".home", ".corp",
    ".intranet", ".localdomain",
)

# (key, display name, registrable domains)
PLATFORMS = (
    ("x", "X (Twitter)", ("x.com", "twitter.com")),
    ("facebook", "Facebook", ("facebook.com", "fb.com", "fb.watch")),
    ("instagram", "Instagram", ("instagram.com",)),
    ("youtube", "YouTube", ("youtube.com", "youtu.be")),
    ("tiktok", "TikTok", ("tiktok.com",)),
    ("reddit", "Reddit", ("reddit.com", "redd.it")),
    ("threads", "Threads", ("threads.net", "threads.com")),
    ("linkedin", "LinkedIn", ("linkedin.com",)),
    ("bluesky", "Bluesky", ("bsky.app",)),
    ("telegram", "Telegram", ("t.me",)),
)
UNKNOWN_PLATFORM = "Not a recognised social platform"


@dataclass
class UrlInfo:
    ok: bool
    submitted: str = ""
    normalized: str = ""
    scheme: str = ""
    host: str = ""
    path: str = ""
    platform_key: str = ""
    platform_name: str = UNKNOWN_PLATFORM
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def detect_platform(host: str) -> tuple[str, str]:
    """Match on exact domain or true subdomain, so 'evil-x.com' never matches 'x.com'."""
    for key, name, domains in PLATFORMS:
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                return key, name
    return "", UNKNOWN_PLATFORM


def _as_ip(host: str) -> Optional[ipaddress._BaseAddress]:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


def parse_url(raw: object) -> UrlInfo:
    """Validate and normalise a URL. Collects problems; never raises."""
    text = raw.strip() if isinstance(raw, str) else ""
    info = UrlInfo(ok=False, submitted=text[:MAX_URL_LENGTH])

    if not text:
        info.errors.append("Enter a URL.")
        return info
    if len(text) > MAX_URL_LENGTH:
        info.errors.append(f"The URL is longer than {MAX_URL_LENGTH} characters.")
        return info
    if _BAD_CHARS.search(text):
        info.errors.append("The URL contains spaces or control characters.")
        return info

    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        info.errors.append("The URL could not be parsed.")
        return info

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        info.errors.append("The URL must start with http:// or https://.")
        return info
    if "@" in parts.netloc:
        info.errors.append("URLs containing a username or password are not accepted.")
        return info
    if port not in ALLOWED_PORTS:
        info.errors.append("Only the standard web ports (80 and 443) are accepted.")
        return info

    host = (parts.hostname or "").rstrip(".")
    if not host:
        info.errors.append("The URL has no host name.")
        return info

    ip = _as_ip(host)
    if ip is not None:
        if not ip.is_global:
            info.errors.append("Private, local and reserved network addresses are not accepted.")
            return info
        ascii_host = str(ip)
    else:
        if "." not in host or host.endswith(_BLOCKED_SUFFIXES):
            info.errors.append("Local, internal and single-label host names are not accepted.")
            return info
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            info.errors.append("The host name is not valid.")
            return info
        if "xn--" in ascii_host:
            info.notes.append(
                "The host name uses internationalised (punycode) characters. Check "
                "that it is the site you expect, as look-alike domains exist."
            )

    netloc = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    keep_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    if keep_port:
        netloc += f":{port}"

    info.ok = True
    info.scheme = scheme
    info.host = ascii_host
    info.path = parts.path or "/"
    info.normalized = urlunsplit((scheme, netloc, info.path, parts.query, ""))
    info.platform_key, info.platform_name = detect_platform(ascii_host)
    if not info.platform_key:
        info.notes.append(
            "This is not a recognised social platform, so it is treated as an "
            "ordinary web page."
        )
    return info


def check_public_host(host: str) -> Optional[str]:
    """Resolve a host and return an error message unless every address is public."""
    try:
        results = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return "The host name could not be resolved."
    addresses = {item[4][0] for item in results}
    if not addresses:
        return "The host name did not resolve to any address."
    for address in addresses:
        ip = _as_ip(address.split("%")[0])
        if ip is None or not ip.is_global:
            return "The host resolves to a private or reserved network address, so it was not contacted."
    return None