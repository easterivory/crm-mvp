from __future__ import annotations

from typing import Any


def normalize_name_part(value: Any) -> str | None:
    normalized = " ".join(str(value or "").strip().split())
    return normalized or None


def split_lead_name(
    value: Any,
    *,
    username: str | None = None,
) -> tuple[str | None, str | None]:
    normalized = normalize_name_part(value)
    if not normalized:
        return None, None

    username_key = str(username or "").strip().removeprefix("@").lower()
    parts = [
        part
        for part in normalized.split()
        if not username_key or part.removeprefix("@").lower() != username_key
    ]
    if not parts:
        return None, None
    return parts[0], normalize_name_part(" ".join(parts[1:]))


def compose_lead_name(first_name: Any, last_name: Any) -> str | None:
    return normalize_name_part(
        " ".join(
            part
            for part in (
                normalize_name_part(first_name),
                normalize_name_part(last_name),
            )
            if part
        )
    )


def resolve_lead_names(lead: Any) -> tuple[str | None, str | None]:
    custom_fields = dict(getattr(lead, "custom_fields", None) or {})
    first_name = normalize_name_part(custom_fields.get("first_name"))
    last_name = normalize_name_part(custom_fields.get("last_name"))
    legacy_first, legacy_last = split_lead_name(
        getattr(lead, "name", None),
        username=getattr(lead, "username", None),
    )
    return first_name or legacy_first, last_name or legacy_last
