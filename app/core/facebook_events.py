from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


FACEBOOK_EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
FACEBOOK_SOURCE_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
FACEBOOK_PARAMETER_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

FACEBOOK_BROWSER_SOURCE_EVENTS = frozenset({"page_view", "telegram_click"})

FACEBOOK_SOURCE_EVENT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "page_view",
        "label": "Просмотр лендинга",
        "delivery": "browser",
        "trigger": "automatic",
    },
    {
        "key": "telegram_click",
        "label": "Переход в Telegram",
        "delivery": "browser",
        "trigger": "automatic",
    },
    {
        "key": "bot_start",
        "label": "Запуск бота",
        "delivery": "server",
        "trigger": "automatic",
    },
    {
        "key": "contact",
        "label": "Получен контакт",
        "delivery": "server",
        "trigger": "automatic",
    },
    {
        "key": "registration",
        "label": "Регистрация",
        "delivery": "server",
        "trigger": "funnel",
    },
    {
        "key": "channel_subscribe",
        "label": "Подписка на канал",
        "delivery": "server",
        "trigger": "funnel",
    },
    {
        "key": "channel_unsubscribe",
        "label": "Отписка от канала",
        "delivery": "server",
        "trigger": "funnel",
    },
    {
        "key": "sale",
        "label": "Продажа",
        "delivery": "server",
        "trigger": "funnel",
    },
    {
        "key": "resale",
        "label": "Повторная продажа",
        "delivery": "server",
        "trigger": "funnel",
    },
    {
        "key": "contact_invite_bot",
        "label": "Приглашение контакта в бота",
        "delivery": "server",
        "trigger": "funnel",
    },
)

FACEBOOK_SOURCE_EVENT_ALIASES = {
    "click": "telegram_click",
    "user_start_bot": "bot_start",
    "subscribe_channel": "channel_subscribe",
    "unsubscribe_channel": "channel_unsubscribe",
}

_DEFAULT_FACEBOOK_EVENT_MAPPINGS: tuple[dict[str, Any], ...] = (
    {
        "source_event": "page_view",
        "event_name": "ViewContent",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "telegram_click",
        "event_name": "Lead",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "registration",
        "event_name": "CompleteRegistration",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "channel_subscribe",
        "event_name": "Subscribe",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "channel_unsubscribe",
        "event_name": "Search",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "sale",
        "event_name": "Purchase",
        "enabled": True,
        "parameters": {
            "value": "{{lead.expected_start_amount}}",
            "currency": "USD",
        },
    },
    {
        "source_event": "resale",
        "event_name": "Purchase",
        "enabled": True,
        "parameters": {
            "value": "{{lead.expected_start_amount}}",
            "currency": "USD",
        },
    },
    {
        "source_event": "bot_start",
        "event_name": "Schedule",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "contact",
        "event_name": "Contact",
        "enabled": True,
        "parameters": {},
    },
    {
        "source_event": "contact_invite_bot",
        "event_name": "AddToWishlist",
        "enabled": True,
        "parameters": {},
    },
)


def default_facebook_event_mappings() -> list[dict[str, Any]]:
    return deepcopy(list(_DEFAULT_FACEBOOK_EVENT_MAPPINGS))


def normalize_facebook_source_event(value: object) -> str:
    normalized = str(value or "").strip().lower()
    normalized = FACEBOOK_SOURCE_EVENT_ALIASES.get(normalized, normalized)
    if not FACEBOOK_SOURCE_EVENT_RE.fullmatch(normalized):
        raise ValueError(
            "Facebook source event must use lowercase Latin letters, numbers, or underscores"
        )
    return normalized


def normalize_facebook_event_mappings(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Facebook event mappings must be a list")
    if len(value) > 20:
        raise ValueError("Facebook event mappings may contain at most 20 entries")

    normalized: list[dict[str, Any]] = []
    source_events: set[str] = set()
    for raw_mapping in value:
        if not isinstance(raw_mapping, dict):
            raise ValueError("Each Facebook event mapping must be an object")
        source_event = normalize_facebook_source_event(raw_mapping.get("source_event"))
        if source_event in source_events:
            raise ValueError(f"Duplicate Facebook source event: {source_event}")
        source_events.add(source_event)

        event_name = str(raw_mapping.get("event_name") or "").strip()
        if not FACEBOOK_EVENT_NAME_RE.fullmatch(event_name):
            raise ValueError(
                "Facebook event name must use Latin letters, numbers, or underscores "
                "and be 1-40 characters long"
            )

        raw_parameters = raw_mapping.get("parameters") or {}
        if not isinstance(raw_parameters, dict):
            raise ValueError(f"Facebook parameters for {source_event} must be an object")
        if len(raw_parameters) > 10:
            raise ValueError(
                f"Facebook event {source_event} may contain at most 10 parameters"
            )
        parameters: dict[str, str] = {}
        for raw_key, raw_value in raw_parameters.items():
            key = str(raw_key or "").strip()
            if not FACEBOOK_PARAMETER_NAME_RE.fullmatch(key):
                raise ValueError(f"Unsupported Facebook parameter name: {key}")
            parameter_value = str(raw_value if raw_value is not None else "").strip()
            if len(parameter_value) > 500:
                raise ValueError(f"Facebook parameter {key} is too long")
            if parameter_value:
                parameters[key] = parameter_value

        normalized.append(
            {
                "source_event": source_event,
                "event_name": event_name,
                "enabled": bool(raw_mapping.get("enabled", True)),
                "parameters": parameters,
            }
        )
    return normalized


def facebook_mapping_for_source(
    mappings: object,
    source_event: object,
) -> dict[str, Any] | None:
    normalized_source = normalize_facebook_source_event(source_event)
    try:
        normalized_mappings = normalize_facebook_event_mappings(mappings)
    except ValueError:
        return None
    for mapping in normalized_mappings:
        if mapping["source_event"] == normalized_source and mapping["enabled"]:
            return mapping
    return None
