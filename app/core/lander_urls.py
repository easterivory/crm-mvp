from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode


UTM_KEYS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
)


def effective_campaign_utm_defaults(
    values: Mapping[str, object] | None,
    *,
    tracking_code: str | None,
    is_facebook_campaign: bool,
) -> dict[str, str]:
    normalized = {
        key: str((values or {}).get(key) or "").strip()
        for key in UTM_KEYS
        if str((values or {}).get(key) or "").strip()
    }
    if is_facebook_campaign:
        normalized.setdefault("utm_source", "facebook")
        normalized.setdefault("utm_medium", "paid_social")
        code = (tracking_code or "").strip()
        if code:
            normalized.setdefault("utm_campaign", code)
    return normalized


def build_lander_public_url(
    *,
    host: str,
    slug: str,
    utm_defaults: Mapping[str, object] | None,
) -> str:
    base_url = f"https://{host.strip().lower().rstrip('.')}/l/{slug}"
    pairs = [
        (key, value)
        for key in UTM_KEYS
        if (value := str((utm_defaults or {}).get(key) or "").strip())
    ]
    query = urlencode(pairs)
    return f"{base_url}?{query}" if query else base_url
