"""Outbound AI requests: explicit trust, public DNS and pinned TLS connections."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from app.core.config import settings


def provider_origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("AI provider URL must be an absolute HTTPS URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(
            "AI provider URL cannot contain credentials, query or fragment"
        )
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def trusted_provider(url: str) -> bool:
    origin = provider_origin(url)
    return any(
        origin == provider_origin(value.strip())
        for value in settings.AI_TRUSTED_PROVIDER_ORIGINS.split(",")
        if value.strip()
    )


def validate_provider_url(url: str) -> str:
    normalized = url.strip().rstrip("/")
    provider_origin(normalized)
    if trusted_provider(normalized):
        return normalized
    parts = urlsplit(normalized)
    if parts.scheme != "https":
        raise ValueError(
            "AI provider requires HTTPS; private origins need server allowlisting"
        )
    try:
        address = ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        if (parts.hostname or "").lower() in {"localhost", "localhost.localdomain"}:
            raise ValueError("Local AI provider requires server allowlisting")
    else:
        if not address.is_global:
            raise ValueError("Private AI provider requires server allowlisting")
    return normalized


async def provider_request(
    method: str, url: str, *, timeout: float, **kwargs
) -> httpx.Response:
    try:
        async with asyncio.timeout(timeout):
            return await _pinned_request(method, url, timeout=timeout, **kwargs)
    except TimeoutError as exc:
        raise httpx.ReadTimeout("AI provider request exceeded its deadline") from exc


def _buffered_decoded_response(response: httpx.Response, body: bytes) -> httpx.Response:
    # aiter_bytes has already decompressed the body. Retaining the wire encoding
    # would make the buffered Response try to decompress the same bytes again.
    headers = httpx.Headers(response.headers)
    headers.pop("content-encoding", None)
    headers.pop("content-length", None)
    return httpx.Response(
        response.status_code, headers=headers, content=body, request=response.request,
    )


async def _pinned_request(
    method: str, url: str, *, timeout: float, **kwargs
) -> httpx.Response:
    """Resolve once and pin the socket address without changing Host or TLS identity."""
    validate_provider_url(url)
    parsed = httpx.URL(url)
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                parsed.host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            ),
            timeout=timeout,
        )
    except (OSError, TimeoutError) as exc:
        raise httpx.ConnectError("AI provider DNS resolution failed") from exc
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or (
        not trusted_provider(url)
        and any(not ipaddress.ip_address(ip).is_global for ip in ips)
    ):
        raise ValueError("AI provider resolved to a non-public address")
    headers = dict(kwargs.pop("headers", {}))
    headers["Host"] = parsed.netloc.decode("ascii")
    last_error = None
    async with httpx.AsyncClient(
        timeout=timeout, trust_env=False, follow_redirects=False
    ) as client:
        for ip in sorted(ips, key=lambda item: ":" in item):
            try:
                async with client.stream(
                    method,
                    parsed.copy_with(host=ip),
                    headers=headers,
                    extensions={"sni_hostname": parsed.host},
                    **kwargs,
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise ValueError("AI provider response exceeds 2 MiB")
                    return _buffered_decoded_response(response, bytes(body))
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_error = exc
    assert last_error is not None
    raise last_error
