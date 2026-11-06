import pytest

from modules import url_validator as uv


def test_valid_public_post_url():
    info = uv.parse_url("https://x.com/someone/status/123")
    assert info.ok
    assert info.platform_key == "x"
    assert info.normalized == "https://x.com/someone/status/123"


def test_subdomain_and_alias_platforms():
    assert uv.parse_url("https://mobile.twitter.com/a/status/1").platform_key == "x"
    assert uv.parse_url("https://youtu.be/abc123").platform_key == "youtube"
    assert uv.parse_url("https://www.instagram.com/p/xyz/").platform_key == "instagram"


def test_lookalike_hosts_are_not_matched():
    assert uv.parse_url("https://evil-x.com/a").platform_key == ""
    assert uv.parse_url("https://x.com.evil.com/a").platform_key == ""
    assert uv.parse_url("https://notyoutube.com/a").platform_key == ""


def test_unsupported_platform_is_allowed_but_labelled():
    info = uv.parse_url("https://example.com/news/1")
    assert info.ok
    assert info.platform_name == uv.UNKNOWN_PLATFORM
    assert any("ordinary web page" in n for n in info.notes)


def test_fragment_removed_and_host_lowercased():
    info = uv.parse_url("HTTPS://X.COM/a/status/1#section")
    assert info.ok
    assert info.normalized == "https://x.com/a/status/1"


@pytest.mark.parametrize("bad", [
    "", "   ", None, 123, "not a url", "ftp://x.com/a", "javascript:alert(1)",
    "file:///etc/passwd", "data:text/html,hi", "https://user:pass@x.com/a",
    "https://@x.com/a", "https://x.com:8080/a", "https:///nohost",
    "https://x.com/has space", "https://x.com/\x00evil", "https://[::1",
    "http://intranet/admin", "http://" + "a" * 3000 + ".com",
])
def test_invalid_urls_rejected(bad):
    info = uv.parse_url(bad)
    assert not info.ok
    assert info.errors


@pytest.mark.parametrize("bad", [
    "http://127.0.0.1/", "http://10.0.0.5/admin", "http://192.168.1.1/",
    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "http://0.0.0.0/", "http://100.64.0.1/",
    "http://[::ffff:127.0.0.1]/", "http://localhost/", "http://printer.local/",
    "http://db.internal/",
])
def test_private_and_local_addresses_rejected(bad):
    assert not uv.parse_url(bad).ok


def test_public_ip_literal_accepted():
    assert uv.parse_url("http://8.8.8.8/").ok


def test_punycode_host_gets_a_warning():
    info = uv.parse_url("https://münchen.example/a")
    assert info.ok
    assert any("look-alike" in n for n in info.notes)


def _fake_resolver(*addresses):
    def fake(host, port, *args, **kwargs):
        return [(2, 1, 6, "", (a, 0)) for a in addresses]
    return fake


def test_public_resolution_passes(monkeypatch):
    monkeypatch.setattr(uv.socket, "getaddrinfo", _fake_resolver("8.8.8.8"))
    assert uv.check_public_host("example.com") is None


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:10.0.0.1"])
def test_private_resolution_blocked(monkeypatch, address):
    monkeypatch.setattr(uv.socket, "getaddrinfo", _fake_resolver(address))
    assert uv.check_public_host("example.com") is not None


def test_mixed_public_and_private_resolution_blocked(monkeypatch):
    monkeypatch.setattr(uv.socket, "getaddrinfo", _fake_resolver("8.8.8.8", "10.0.0.1"))
    assert uv.check_public_host("example.com") is not None


def test_unresolvable_host_reported(monkeypatch):
    def boom(*args, **kwargs):
        raise uv.socket.gaierror("no such host")
    monkeypatch.setattr(uv.socket, "getaddrinfo", boom)
    assert "could not be resolved" in uv.check_public_host("nonexistent.example")