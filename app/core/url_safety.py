"""SSRF guard and bounded fetcher for server-side requests to user-supplied URLs.

Why: in the cloud the worker holds an IAM role whose credentials sit behind a link-local metadata
endpoint, and RDS/Qdrant sit on private addresses. A user-supplied URL (or a redirect) pointing there
would turn the ingester into a credential/data exfiltration tool, because fetched text is searchable.
Security groups cannot block link-local addresses, so the check lives here.

What a guarded fetch does:
  * every hop (the first request and each redirect) is validated and its host is resolved once;
  * the connection goes to that validated IP address, with the original Host header and TLS server
    name, so a second DNS lookup cannot send the request somewhere else (DNS rebinding);
  * the body is streamed and cut off at WEB_MAX_BYTES (after decompression);
  * one deadline (WEB_FETCH_TIMEOUT_S) covers all redirects and the whole body.
"""
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.core.config import settings

ALLOWED_PORTS = {None, 80, 443}
CONNECT_TIMEOUT_S = 5.0


class UnsafeURLError(ValueError):
    """ValueError subclass so the ingest runner treats it as permanent (never retried).
    Messages are fixed text and never include the URL."""


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False  # fail closed on anything we cannot parse
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolve_public(url: str):
    """Validate the URL and return (parsed, [public addresses]). Raises UnsafeURLError otherwise."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURLError("URL must be http(s) with a host")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URL must not embed credentials")
    try:
        port = parsed.port
    except ValueError:
        raise UnsafeURLError("URL has an invalid port") from None
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError("URL port is not allowed")
    try:
        infos = socket.getaddrinfo(parsed.hostname, port or (80 if parsed.scheme == "http" else 443),
                                   type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError("URL host could not be resolved") from None
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or not all(_is_public(a) for a in addresses):
        raise UnsafeURLError("URL resolves to a non-public address")
    return parsed, addresses


def assert_public_url(url: str) -> None:
    resolve_public(url)


def _pinned_url(parsed, address: str) -> str:
    host = f"[{address}]" if ":" in address else address
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse((parsed.scheme, netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def _read_limited(response: httpx.Response, deadline: float, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise UnsafeURLError("Response is too large")
    body = bytearray()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise UnsafeURLError("Response is too large")
        if time.monotonic() > deadline:
            raise UnsafeURLError("Fetch took too long")
    return bytes(body)


def _fetch_one(url: str, deadline: float, max_bytes: int, transport, headers) -> httpx.Response:
    parsed, addresses = resolve_public(url)
    last_error: Exception | None = None
    for address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UnsafeURLError("Fetch took too long")
        timeout = httpx.Timeout(remaining, connect=min(CONNECT_TIMEOUT_S, remaining))
        request_headers = {**(headers or {}), "Host": parsed.netloc}
        # sni_hostname makes TLS use (and verify the certificate against) the real host name
        # although we connect to the validated IP address.
        extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
        try:
            with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as client:
                with client.stream("GET", _pinned_url(parsed, address), headers=request_headers,
                                   extensions=extensions) as response:
                    if response.is_redirect:
                        return httpx.Response(response.status_code, headers=response.headers,
                                              request=response.request)
                    body = _read_limited(response, deadline, max_bytes)
                    kept = [(k, v) for k, v in response.headers.multi_items()
                            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                    return httpx.Response(response.status_code, headers=kept, content=body,
                                          request=response.request)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc  # try the next validated address
    raise last_error or UnsafeURLError("URL host could not be reached")


def fetch_public(url: str, *, max_redirects: int = 5, max_bytes: int | None = None,
                 total_timeout_s: float | None = None, headers: dict | None = None,
                 transport: httpx.BaseTransport | None = None) -> httpx.Response:
    """GET with validated, IP-pinned connections, a body size cap and one total deadline.

    Returns a fully read httpx.Response (so `.text` and `.raise_for_status()` work). Raises UnsafeURLError for a
    blocked destination, an oversized body, a slow fetch or too many redirects.
    """
    max_bytes = settings.web_max_bytes if max_bytes is None else max_bytes
    total = settings.web_fetch_timeout_s if total_timeout_s is None else total_timeout_s
    deadline = time.monotonic() + total
    for _ in range(max_redirects + 1):
        response = _fetch_one(url, deadline, max_bytes, transport, headers)
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        url = urljoin(url, location)
    raise UnsafeURLError("Too many redirects")
