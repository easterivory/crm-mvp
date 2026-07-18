from __future__ import annotations

from types import MappingProxyType


DEFAULT_CONFIDENCE_WEIGHTS = MappingProxyType(
    {
        "suspicious_first_name": 15,
        "suspicious_last_name": 10,
        "invalid_phone": 25,
        "geo_missing": 10,
        "geo_conflict": 20,
        "card_missing": 20,
        "card_unknown": 10,
        "amount_below_minimum": 14,
        "amount_unknown": 10,
        "missing_tracking_link": 20,
        "reask": 20,
        "long_response_pause": 20,
        "broadcast_followup": 20,
        "probable_duplicate": 40,
    }
)

DEFAULT_CONFIDENCE_THRESHOLDS = MappingProxyType(
    {
        "high_min": 80,
        "medium_min": 50,
    }
)


def merged_confidence_weights(overrides: dict | None) -> dict[str, int]:
    result = dict(DEFAULT_CONFIDENCE_WEIGHTS)
    for key, value in (overrides or {}).items():
        if key in result and isinstance(value, int) and not isinstance(value, bool):
            result[key] = max(0, min(value, 100))
    return result


def merged_confidence_thresholds(overrides: dict | None) -> dict[str, int]:
    result = dict(DEFAULT_CONFIDENCE_THRESHOLDS)
    for key, value in (overrides or {}).items():
        if key in result and isinstance(value, int) and not isinstance(value, bool):
            result[key] = max(0, min(value, 100))
    if result["medium_min"] > result["high_min"]:
        return dict(DEFAULT_CONFIDENCE_THRESHOLDS)
    return result
