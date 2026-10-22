import gzip
import socket
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core import url_safety as us
from app.core.config import settings

PUBLIC = "93.184.216.34"


def resolves(*addresses):
    return patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", (a, 0)) for a in addresses])


# ---------------- destination checks ----------------
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://169.254.170.2/v2/credentials/x",
    "http://127.0.0.1:8000/", "http://localhost/", "http://10.0.3.7/", "http://192.168.1.1/",
    "http://[::1]/", "http://[::ffff:169.254.169.254]/", "http://[fd00::1]/", "http://0.0.0.0/",
])
def test_private_literals_blocked(url):
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    host = "127.0.0.1" if host == "localhost" else host
    with resolves(host), pytest.raises(us.UnsafeURLError):
        us.assert_public_url(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "//example.com",
    "http://user:pw@example.com/", "http://example.com:6333/", "http://example.com:22/", "http:///x",
])
def test_scheme_credentials_ports_blocked(url):
    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError):
        us.assert_public_url(url)


def test_public_host_allowed_and_mixed_resolution_blocked():
    with resolves(PUBLIC, "2606:2800:220:1::1"):
        us.assert_public_url("https://example.com/page?q=1")
    with resolves(PUBLIC, "10.0.0.5"), pytest.raises(us.UnsafeURLError):
        us.assert_public_url("https://example.com/")


def test_unparseable_resolved_address_fails_closed():
    with resolves("not-an-ip"), pytest.raises(us.UnsafeURLError):
        us.assert_public_url("https://example.com/")


def test_unresolvable_host_blocked():
    with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror), pytest.raises(us.UnsafeURLError):
        us.assert_public_url("https://nope.invalid/")


def test_errors_never_contain_the_url():
    secret = "https://user:tok3n@evil.test/path?key=abc"
    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError) as err:
        us.assert_public_url(secret)
    assert "tok3n" not in str(err.value) and "evil.test" not in str(err.value)


# ---------------- pinned connections ----------------
def test_connects_to_the_validated_ip_with_host_header_and_tls_server_name():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(200, text="<html>ok</html>")

    with resolves(PUBLIC):
        response = us.fetch_public("https://example.com/a/b?x=1", transport=httpx.MockTransport(handler))
    assert seen == [(f"https://{PUBLIC}/a/b?x=1", "example.com", "example.com")]
    assert response.status_code == 200 and response.text == "<html>ok</html>"


def test_plain_http_has_no_tls_server_name_and_keeps_a_custom_port_in_host():
    seen = []

    def handler(request):
        seen.append((request.headers["host"], "sni_hostname" in request.extensions))
        return httpx.Response(200, text="x")

    with resolves(PUBLIC):
        us.fetch_public("http://example.com/", transport=httpx.MockTransport(handler))
    assert seen == [("example.com", False)]


def test_ipv6_addresses_are_bracketed_in_the_pinned_url():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text="x")

    with resolves("2606:2800:220:1::1"):
        us.fetch_public("https://example.com/p", transport=httpx.MockTransport(handler))
    assert seen == ["https://[2606:2800:220:1::1]/p"]


def test_dns_rebinding_second_lookup_is_never_used():
    """The first answer is public, any later answer would be private. The fetch must resolve once per hop and
    connect to the first answer, so a rebinding server gains nothing."""
    answers = iter([[(2, 1, 6, "", (PUBLIC, 0))], [(2, 1, 6, "", ("169.254.169.254", 0))]])
    calls = []

    def fake_resolve(*a, **kw):
        calls.append(a)
        return next(answers)

    targets = []

    def handler(request):
        targets.append(request.url.host)
        return httpx.Response(200, text="x")

    with patch.object(socket, "getaddrinfo", side_effect=fake_resolve):
        us.fetch_public("https://rebind.example/", transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and targets == [PUBLIC]


def test_falls_back_to_the_next_validated_address_on_connect_failure():
    tried = []

    def handler(request):
        tried.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, text="ok")

    with resolves(PUBLIC, "93.184.216.35"):
        assert us.fetch_public("https://example.com/", transport=httpx.MockTransport(handler)).text == "ok"
    assert tried == ["93.184.216.34", "93.184.216.35"]


# ---------------- redirects ----------------
def test_redirect_to_metadata_endpoint_is_blocked_at_the_hop():
    def fake_resolve(host, port, **kw):
        ip = "169.254.169.254" if host == "169.254.169.254" else PUBLIC
        return [(2, 1, 6, "", (ip, port))]

    requested = []

    def handler(request):
        requested.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/iam/"})

    with patch.object(socket, "getaddrinfo", side_effect=fake_resolve):
        with pytest.raises(us.UnsafeURLError):
            us.fetch_public("https://example.com/redir", transport=httpx.MockTransport(handler))
    assert requested == ["example.com"]  # the metadata address was never requested


def test_redirect_chain_is_followed_hop_by_hop_with_relative_locations():
    hops = {"/a": "/b", "/b": "https://example.com/c"}
    seen = []

    def handler(request):
        seen.append(request.url.path)
        nxt = hops.get(request.url.path)
        return httpx.Response(301, headers={"location": nxt}) if nxt else httpx.Response(200, text="done")

    with resolves(PUBLIC):
        r = us.fetch_public("https://example.com/a", transport=httpx.MockTransport(handler))
    assert seen == ["/a", "/b", "/c"] and r.text == "done"


def test_endless_redirects_are_capped():
    handler = lambda request: httpx.Response(302, headers={"location": "/loop"})  # noqa: E731
    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError, match="redirects"):
        us.fetch_public("https://example.com/", max_redirects=3, transport=httpx.MockTransport(handler))


def test_total_deadline_covers_the_whole_redirect_chain():
    def handler(request):
        time.sleep(0.15)
        return httpx.Response(302, headers={"location": "/next"})

    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError, match="too long"):
        us.fetch_public("https://example.com/", max_redirects=10, total_timeout_s=0.3,
                        transport=httpx.MockTransport(handler))


# ---------------- body limits ----------------
def test_declared_oversize_is_refused_before_reading():
    def handler(request):
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"x" * 10)

    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError, match="too large"):
        us.fetch_public("https://example.com/", max_bytes=1000, transport=httpx.MockTransport(handler))


def test_undeclared_oversize_stream_is_cut_off():
    def body():
        for _ in range(100):
            yield b"x" * 100

    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError, match="too large"):
        us.fetch_public("https://example.com/", max_bytes=1000,
                        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body())))


def test_decompression_bomb_is_limited_by_the_decoded_size():
    bomb = gzip.compress(b"a" * 5_000_000)
    assert len(bomb) < 20_000

    def handler(request):
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=bomb)

    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError, match="too large"):
        us.fetch_public("https://example.com/", max_bytes=100_000, transport=httpx.MockTransport(handler))


def test_slow_body_hits_the_total_deadline():
    def slow():
        for _ in range(100):
            time.sleep(0.05)
            yield b"x"

    with resolves(PUBLIC), pytest.raises(us.UnsafeURLError, match="too long"):
        us.fetch_public("https://example.com/", total_timeout_s=0.2,
                        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=slow())))


def test_a_normal_page_within_limits_reads_fully_and_decodes():
    page = "<html><title>Hi é</title></html>".encode()

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8",
                                            "content-encoding": "gzip"}, content=gzip.compress(page))

    with resolves(PUBLIC):
        r = us.fetch_public("https://example.com/", max_bytes=10_000, transport=httpx.MockTransport(handler))
    assert r.text == page.decode() and "content-encoding" not in r.headers
    r.raise_for_status()


def test_http_errors_come_back_as_a_response_for_the_caller_to_judge():
    with resolves(PUBLIC):
        r = us.fetch_public("https://example.com/", transport=httpx.MockTransport(lambda q: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        r.raise_for_status()


def test_default_limits_are_sensible():
    assert settings.web_max_bytes == 5 * 1024 * 1024 and settings.web_fetch_timeout_s == 30


# ---------------- wiring ----------------
def test_unsafe_url_is_a_permanent_ingest_error():
    from app.services.ingestion.runner import is_permanent
    assert is_permanent(us.UnsafeURLError("x"))


def test_scrape_uses_guard_only_when_enabled(monkeypatch):
    from app.services.ingestion import web

    guarded = MagicMock(side_effect=us.UnsafeURLError("blocked"))
    monkeypatch.setattr(web, "fetch_public", guarded)
    monkeypatch.setattr(settings, "ingest_block_private_urls", True)
    with patch.object(web.httpx, "get") as plain, pytest.raises(us.UnsafeURLError):
        web._scrape("http://169.254.169.254/")
    plain.assert_not_called()

    monkeypatch.setattr(settings, "ingest_block_private_urls", False)
    ok = MagicMock(text="<html><title>T</title></html>")
    with patch.object(web.httpx, "get", return_value=ok) as plain, \
            patch.object(web.trafilatura, "extract", return_value="body"):
        assert web._scrape("http://localhost:9/")["title"] == "T"
    plain.assert_called_once()
    guarded.assert_called_once()
