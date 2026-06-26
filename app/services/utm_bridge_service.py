from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


QueryParamInput = Mapping[str, Any] | Iterable[tuple[str, Any]]


class UtmBridgeService:
    """Short-lived Redis bridge between web landing visits and Telegram starts."""

    KEY_PREFIX = "utm_bridge:"
    TTL_SECONDS = 15 * 60
    START_KEY_PREFIX = "start_"
    LANDER_START_PREFIX = "ls_"

    async def store_query_params(
        self,
        query_params: QueryParamInput | None,
        *,
        browser_context: Mapping[str, Any] | None = None,
    ) -> str:
        payload = self.build_bridge_payload(query_params, browser_context=browser_context)
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

    async def store_lander_start(
        self,
        *,
        ref_code: str,
        query_params: QueryParamInput | None,
        browser_context: Mapping[str, Any] | None = None,
    ) -> str:
        key = f"{self.START_KEY_PREFIX}{uuid.uuid4().hex[:10]}"
        payload = {
            "ref_code": ref_code,
            "params": self.build_bridge_payload(
                query_params,
                browser_context=browser_context,
            ),
        }
        redis = await get_redis()
        await redis.setex(
            self._redis_key(key),
            self.TTL_SECONDS,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        return key

    async def load_lander_start(self, key: str) -> tuple[str, dict[str, Any]] | None:
        normalized_key = self.normalize_start_key(key)
        if normalized_key is None:
            return None

        redis = await get_redis()
        raw = await redis.get(self._redis_key(normalized_key))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid landing start bridge JSON payload key=%s", normalized_key)
            return None
        if not isinstance(payload, dict):
            return None
        ref_code = payload.get("ref_code")
        params = payload.get("params")
        if not isinstance(ref_code, str) or not ref_code.strip() or not isinstance(params, dict):
            return None
        return ref_code.strip(), params

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

    @classmethod
    def normalize_start_key(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        if not normalized.startswith(cls.START_KEY_PREFIX):
            return None
        suffix = normalized.removeprefix(cls.START_KEY_PREFIX)
        if len(suffix) != 10:
            return None
        try:
            int(suffix, 16)
        except ValueError:
            return None
        return f"{cls.START_KEY_PREFIX}{suffix.lower()}"

    @classmethod
    def build_lander_start_payload(cls, tracking_link_id: UUID, start_key: str) -> str:
        """Build a Telegram-safe payload with durable campaign attribution."""
        normalized_key = cls.normalize_start_key(start_key)
        if normalized_key is None:
            raise ValueError("Invalid landing start key")
        return (
            f"{cls.LANDER_START_PREFIX}{tracking_link_id.hex}_"
            f"{normalized_key.removeprefix(cls.START_KEY_PREFIX)}"
        )

    @classmethod
    def parse_lander_start_payload(cls, value: str | None) -> tuple[UUID, str] | None:
        normalized = (value or "").strip().lower()
        prefix_length = len(cls.LANDER_START_PREFIX)
        expected_length = prefix_length + 32 + 1 + 10
        if not normalized.startswith(cls.LANDER_START_PREFIX) or len(normalized) != expected_length:
            return None

        tracking_link_hex = normalized[prefix_length : prefix_length + 32]
        separator_index = prefix_length + 32
        start_suffix = normalized[separator_index + 1 :]
        if normalized[separator_index] != "_":
            return None
        try:
            tracking_link_id = UUID(hex=tracking_link_hex)
        except ValueError:
            return None
        start_key = cls.normalize_start_key(f"{cls.START_KEY_PREFIX}{start_suffix}")
        if start_key is None:
            return None
        return tracking_link_id, start_key

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
    def build_bridge_payload(
        cls,
        query_params: QueryParamInput | None,
        *,
        browser_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = cls.normalize_query_params(query_params)
        payload.update(cls.normalize_facebook_context(browser_context, payload))
        return payload

    @classmethod
    def normalize_facebook_context(
        cls,
        browser_context: Mapping[str, Any] | None,
        query_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        if browser_context is None:
            browser_context = {}
        query_payload = query_payload or {}

        fbp = cls._clean_context_value(browser_context.get("fbp") or browser_context.get("_fbp"), 500)
        fbc = cls._clean_context_value(browser_context.get("fbc") or browser_context.get("_fbc"), 500)
        fbclid = cls._clean_context_value(query_payload.get("fbclid"), 500)
        if fbc is None and fbclid is not None:
            fbc = f"fb.1.{int(time.time() * 1000)}.{fbclid}"

        context: dict[str, str] = {}
        if fbp is not None:
            context["fbp"] = fbp
        if fbc is not None:
            context["fbc"] = fbc

        user_agent = cls._clean_context_value(
            browser_context.get("client_user_agent") or browser_context.get("user_agent"),
            1000,
        )
        if user_agent is not None:
            context["client_user_agent"] = user_agent

        client_ip = cls._clean_context_value(
            browser_context.get("client_ip_address") or browser_context.get("client_ip"),
            100,
        )
        if client_ip is not None:
            context["client_ip_address"] = client_ip

        return context

    @staticmethod
    def _clean_context_value(value: Any, max_length: int) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized[:max_length]

    @classmethod
    def _redis_key(cls, utm_key: str) -> str:
        return f"{cls.KEY_PREFIX}{utm_key}"
