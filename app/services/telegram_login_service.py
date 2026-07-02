from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

from app.core.redis import get_redis


LOGIN_SESSION_TTL_SECONDS = 300
LOGIN_START_PREFIX = "crm_login_"


@dataclass(frozen=True, slots=True)
class TelegramLoginSession:
    status: str
    telegram_id: int | None = None


class TelegramLoginSessionService:
    """One-time Telegram login sessions that do not depend on widget domains."""

    async def create(self) -> str:
        token = secrets.token_urlsafe(24)
        redis = await get_redis()
        await redis.set(
            self._key(token),
            json.dumps({"status": "pending"}),
            ex=LOGIN_SESSION_TTL_SECONDS,
        )
        return token

    async def get(self, token: str) -> TelegramLoginSession | None:
        redis = await get_redis()
        raw = await redis.get(self._key(token))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        telegram_id = payload.get("telegram_id")
        return TelegramLoginSession(
            status=str(payload.get("status") or "pending"),
            telegram_id=int(telegram_id) if telegram_id is not None else None,
        )

    async def approve(self, token: str, telegram_id: int) -> bool:
        current = await self.get(token)
        if current is None or current.status != "pending":
            return False
        redis = await get_redis()
        await redis.set(
            self._key(token),
            json.dumps({"status": "approved", "telegram_id": telegram_id}),
            ex=LOGIN_SESSION_TTL_SECONDS,
        )
        return True

    async def consume(self, token: str) -> TelegramLoginSession | None:
        redis = await get_redis()
        raw = await redis.getdel(self._key(token))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        telegram_id = payload.get("telegram_id")
        return TelegramLoginSession(
            status=str(payload.get("status") or "pending"),
            telegram_id=int(telegram_id) if telegram_id is not None else None,
        )

    @staticmethod
    def start_argument(token: str) -> str:
        return f"{LOGIN_START_PREFIX}{token}"

    @staticmethod
    def parse_start_argument(argument: str | None) -> str | None:
        value = (argument or "").strip()
        if not value.startswith(LOGIN_START_PREFIX):
            return None
        token = value.removeprefix(LOGIN_START_PREFIX)
        return token if 20 <= len(token) <= 48 else None

    @staticmethod
    def _key(token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"telegram-login:{digest}"
