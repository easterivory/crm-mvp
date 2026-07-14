from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit


TELEGRAM_PUBLIC_WEB_HOST = "telegram.me"
TELEGRAM_WEB_HOST_ALIASES = frozenset(
    {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
)


def build_telegram_bot_start_link(
    bot_username: str,
    start_parameter: str,
) -> str:
    username = (bot_username or "").removeprefix("@").strip()
    parameter = (start_parameter or "").strip()
    path = f"/{quote(username, safe='')}"
    query = f"start={quote(parameter, safe='')}"
    return urlunsplit(("https", TELEGRAM_PUBLIC_WEB_HOST, path, query, ""))


def canonicalize_telegram_web_link(value: str | None) -> str | None:
    """Use the browser-safe Telegram host without changing link semantics."""

    if value is None:
        return None
    raw_value = value.strip()
    if not raw_value:
        return raw_value

    candidate = raw_value
    lowered = raw_value.lower()
    if any(
        lowered == host or lowered.startswith(f"{host}/")
        for host in TELEGRAM_WEB_HOST_ALIASES
    ):
        candidate = f"https://{raw_value}"

    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return raw_value

    if parsed.scheme.lower() not in {"http", "https"}:
        return raw_value
    if hostname not in TELEGRAM_WEB_HOST_ALIASES:
        return raw_value

    return urlunsplit(
        (
            "https",
            TELEGRAM_PUBLIC_WEB_HOST,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
