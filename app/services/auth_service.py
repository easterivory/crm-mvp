from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.bot_repository import BotRepository


class AuthService:
    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db
        self.bot_repo = BotRepository(db) if db is not None else None

    async def verify_telegram_auth_for_bot(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        auth_data: Mapping[str, object],
        max_age_seconds: int | None = 86400,
        is_web_app: bool | None = None,
    ) -> bool:
        if self.bot_repo is None:
            return False
        token = await self.bot_repo.get_bot_token_by_id(bot_id, project_id)
        if not token:
            return False
        return self.verify_telegram_auth(
            auth_data,
            bot_token=token,
            max_age_seconds=max_age_seconds,
            is_web_app=is_web_app,
        )

    @staticmethod
    def verify_telegram_auth(
        auth_data: Mapping[str, object],
        bot_token: str | None = None,
        max_age_seconds: int | None = 86400,
        is_web_app: bool | None = None,
    ) -> bool:
        token = (bot_token or settings.BUYER_BOT_TOKEN or "").strip()
        received_hash = str(auth_data.get("hash") or "").strip()
        if not token or not received_hash:
            return False

        if not AuthService._auth_date_is_valid(auth_data, max_age_seconds):
            return False

        data_check_string = AuthService._build_data_check_string(auth_data)
        if not data_check_string:
            return False

        web_app_mode = (
            is_web_app
            if is_web_app is not None
            else any(key in auth_data for key in ("query_id", "user", "chat", "chat_type"))
        )
        secret_key = AuthService._web_app_secret_key(token) if web_app_mode else AuthService._login_widget_secret_key(token)
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_hash, received_hash.lower())

    @staticmethod
    def _build_data_check_string(auth_data: Mapping[str, object]) -> str:
        pairs = []
        for key, value in auth_data.items():
            if key == "hash" or value is None:
                continue
            pairs.append((str(key), AuthService._stringify_telegram_value(value)))
        pairs.sort(key=lambda item: item[0])
        return "\n".join(f"{key}={value}" for key, value in pairs)

    @staticmethod
    def _stringify_telegram_value(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list)):
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        return str(value)

    @staticmethod
    def _login_widget_secret_key(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    @staticmethod
    def _web_app_secret_key(token: str) -> bytes:
        return hmac.new(
            b"WebAppData",
            token.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    @staticmethod
    def _auth_date_is_valid(
        auth_data: Mapping[str, object],
        max_age_seconds: int | None,
    ) -> bool:
        if max_age_seconds is None:
            return True
        try:
            auth_date = int(str(auth_data.get("auth_date") or ""))
        except ValueError:
            return False
        now = int(time.time())
        return auth_date <= now + 60 and now - auth_date <= max_age_seconds
