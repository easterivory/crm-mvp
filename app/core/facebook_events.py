from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import UUID


FACEBOOK_EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
FACEBOOK_SOURCE_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
FACEBOOK_PARAMETER_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

FACEBOOK_BROWSER_SOURCE_EVENTS = frozenset({"page_view", "telegram_click"})
FACEBOOK_AUTOMATIC_SOURCE_EVENTS = frozenset(
    {*FACEBOOK_BROWSER_SOURCE_EVENTS, "bot_start", "contact"}
)
FACEBOOK_EVENT_TRIGGER_TYPES = frozenset(
    {"funnel_action", "lead_status", "lead_tag"}
)

FACEBOOK_SOURCE_EVENT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "page_view",
        "label": "Просмотр лендинга",
        "delivery": "browser",
        "trigger": "automatic",
        "trigger_description": "Открытие лендинга в браузере",
    },
    {
        "key": "telegram_click",
        "label": "Переход в Telegram",
        "delivery": "browser",
        "trigger": "automatic",
        "trigger_description": "Клик по кнопке перехода в Telegram",
    },
    {
        "key": "bot_start",
        "label": "Запуск бота",
        "delivery": "server",
        "trigger": "automatic",
        "trigger_description": "Команда /start по ссылке этой кампании",
    },
    {
        "key": "contact",
        "label": "Получен контакт",
        "delivery": "server",
        "trigger": "automatic",
        "trigger_description": "Телефон сохранён после отправки контакта",
    },
    {
        "key": "registration",
        "label": "Регистрация",
        "delivery": "server",
        "trigger": "funnel",
        "trigger_description": "CRM-действие, переход в статус или добавление тега",
    },
    {
        "key": "channel_subscribe",
        "label": "Подписка на канал",
        "delivery": "server",
        "trigger": "funnel",
        "trigger_description": "CRM-действие, переход в статус или добавление тега",
    },
    {
        "key": "channel_unsubscribe",
        "label": "Отписка от канала",
        "delivery": "server",
        "trigger": "funnel",
        "trigger_description": "CRM-действие, переход в статус или добавление тега",
    },
    {
        "key": "sale",
        "label": "Первый депозит / продажа",
        "delivery": "server",
        "trigger": "funnel",
        "trigger_description": "CRM-действие, переход в статус или добавление тега",
    },
    {
        "key": "resale",
        "label": "Повторный депозит / продажа",
        "delivery": "server",
        "trigger": "funnel",
        "trigger_description": "CRM-действие, переход в статус или добавление тега",
    },
    {
        "key": "contact_invite_bot",
        "label": "Приглашение контакта в бота",
        "delivery": "server",
        "trigger": "funnel",
        "trigger_description": "CRM-действие, переход в статус или добавление тега",
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
        "triggers": [],
    },
    {
        "source_event": "telegram_click",
        "event_name": "Lead",
        "enabled": True,
        "parameters": {},
        "triggers": [],
    },
    {
        "source_event": "registration",
        "event_name": "CompleteRegistration",
        "enabled": True,
        "parameters": {},
        "triggers": [{"type": "funnel_action"}],
    },
    {
        "source_event": "channel_subscribe",
        "event_name": "Subscribe",
        "enabled": True,
        "parameters": {},
        "triggers": [{"type": "funnel_action"}],
    },
    {
        "source_event": "channel_unsubscribe",
        "event_name": "Search",
        "enabled": True,
        "parameters": {},
        "triggers": [{"type": "funnel_action"}],
    },
    {
        "source_event": "sale",
        "event_name": "Purchase",
        "enabled": True,
        "parameters": {
            "value": "{{lead.expected_start_amount}}",
            "currency": "USD",
        },
        "triggers": [{"type": "funnel_action"}],
    },
    {
        "source_event": "resale",
        "event_name": "Purchase",
        "enabled": True,
        "parameters": {
            "value": "{{lead.expected_start_amount}}",
            "currency": "USD",
        },
        "triggers": [{"type": "funnel_action"}],
    },
    {
        "source_event": "bot_start",
        "event_name": "Schedule",
        "enabled": True,
        "parameters": {},
        "triggers": [],
    },
    {
        "source_event": "contact",
        "event_name": "Contact",
        "enabled": True,
        "parameters": {},
        "triggers": [],
    },
    {
        "source_event": "contact_invite_bot",
        "event_name": "AddToWishlist",
        "enabled": True,
        "parameters": {},
        "triggers": [{"type": "funnel_action"}],
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

        triggers = normalize_facebook_event_triggers(
            raw_mapping.get("triggers") if "triggers" in raw_mapping else None,
            source_event=source_event,
        )

        normalized.append(
            {
                "source_event": source_event,
                "event_name": event_name,
                "enabled": bool(raw_mapping.get("enabled", True)),
                "parameters": parameters,
                "triggers": triggers,
            }
        )
    return normalized


def normalize_facebook_event_triggers(
    value: object,
    *,
    source_event: str,
) -> list[dict[str, str]]:
    if source_event in FACEBOOK_AUTOMATIC_SOURCE_EVENTS:
        if value not in (None, []):
            raise ValueError(
                f"Automatic Facebook source event {source_event} cannot have custom triggers"
            )
        return []

    # Existing campaigns predate explicit trigger rules. Their server events
    # were fired by funnel CRM actions, so missing data must preserve that path.
    if value is None:
        return [{"type": "funnel_action"}]
    if not isinstance(value, list):
        raise ValueError("Facebook event triggers must be a list")
    if len(value) > 10:
        raise ValueError("Facebook event mappings may contain at most 10 triggers")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_trigger in value:
        if not isinstance(raw_trigger, dict):
            raise ValueError("Each Facebook event trigger must be an object")
        trigger_type = str(raw_trigger.get("type") or "").strip().lower()
        if trigger_type not in FACEBOOK_EVENT_TRIGGER_TYPES:
            raise ValueError(f"Unsupported Facebook event trigger type: {trigger_type}")

        trigger_value = ""
        if trigger_type in {"lead_status", "lead_tag"}:
            raw_value = str(raw_trigger.get("value") or "").strip()
            try:
                trigger_value = str(UUID(raw_value))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Facebook trigger {trigger_type} requires a valid UUID value"
                ) from exc

        identity = (trigger_type, trigger_value)
        if identity in seen:
            raise ValueError(
                f"Duplicate Facebook event trigger: {trigger_type}:{trigger_value}"
            )
        seen.add(identity)
        trigger = {"type": trigger_type}
        if trigger_value:
            trigger["value"] = trigger_value
        normalized.append(trigger)
    return normalized


def facebook_mapping_has_trigger(
    mapping: dict[str, Any],
    *,
    trigger_type: str,
    trigger_value: object = None,
) -> bool:
    normalized_type = str(trigger_type or "").strip().lower()
    normalized_value = str(trigger_value or "").strip().lower()
    for trigger in mapping.get("triggers") or []:
        if not isinstance(trigger, dict):
            continue
        if str(trigger.get("type") or "").strip().lower() != normalized_type:
            continue
        configured_value = str(trigger.get("value") or "").strip().lower()
        if configured_value == normalized_value:
            return True
    return False


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
