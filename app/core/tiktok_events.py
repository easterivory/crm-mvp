from app.core.facebook_events import normalize_facebook_event_mappings


def default_tiktok_mappings() -> list[dict]:
    names = {
        "page_view": "ViewContent", "telegram_click": "TelegramClick", "bot_start": "Contact",
        "contact": "SubmitForm", "registration": "CompleteRegistration",
        "channel_subscribe": "Subscribe", "sale": "Purchase", "resale": "Purchase",
    }
    return normalize_facebook_event_mappings([
        {"source_event": source, "event_name": name, "enabled": True,
         "parameters": {"value": "{{lead.expected_start_amount}}", "currency": "USD"} if source in {"sale", "resale"} else {}}
        for source, name in names.items()
    ])


def normalize_tiktok_mappings(value: object) -> list[dict]:
    # CRM triggers have the same semantics for both destinations; event names
    # and integration credentials remain independent.
    return normalize_facebook_event_mappings(value)
