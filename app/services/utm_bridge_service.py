from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


QueryParamInput = Mapping[str, Any] | Iterable[tuple[str, Any]]


class UtmBridgeService:
    """Short-lived Redis bridge between web landing visits and Telegram starts."""

    KEY_PREFIX = "utm_bridge:"
    TTL_SECONDS = 15 * 60

    async def store_query_params(self, query_params: QueryParamInput | None) -> str:
        payload = self.normalize_query_params(query_params)
        utm_key = f"utm_{uuid.uuid4().hex[:8]}"
        redis = await get_redis()
        await redis.setex(
            self._redis_key(utm_key),
            self.TTL_SECONDS,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        logger.debug("Stored UTM bridge payload key=%s keys=%s", utm_key, sorted(payload))
        return utm_key

    async def load_query_params(self, utm_key: str) -> dict[str, Any] | None:
        normalized_key = self.normalize_utm_key(utm_key)
        if normalized_key is None:
            return None

        redis = await get_redis()
        raw = await redis.get(self._redis_key(normalized_key))
        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid UTM bridge JSON payload key=%s", normalized_key)
            return None
        if not isinstance(payload, dict):
            logger.warning("Invalid UTM bridge payload type key=%s", normalized_key)
            return None
        return payload

    @classmethod
    def normalize_utm_key(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        if not normalized.startswith("utm_"):
            return None
        suffix = normalized.removeprefix("utm_")
        if len(suffix) != 8:
            return None
        try:
            int(suffix, 16)
        except ValueError:
            return None
        return f"utm_{suffix.lower()}"

    @staticmethod
    def normalize_query_params(query_params: QueryParamInput | None) -> dict[str, Any]:
        if query_params is None:
            return {}

        if hasattr(query_params, "multi_items"):
            items = list(query_params.multi_items())  # type: ignore[attr-defined]
        elif isinstance(query_params, Mapping):
            items = list(query_params.items())
        else:
            items = list(query_params)

        normalized: dict[str, Any] = {}
        for raw_key, raw_value in items:
            key = str(raw_key).strip()
            if not key:
                continue
            value = "" if raw_value is None else str(raw_value)
            existing = normalized.get(key)
            if existing is None:
                normalized[key] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                normalized[key] = [existing, value]
        return normalized

    @classmethod
    def _redis_key(cls, utm_key: str) -> str:
        return f"{cls.KEY_PREFIX}{utm_key}"
