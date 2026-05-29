"""
BotService - project-scoped Telegram bot management.
"""
import logging
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.core.config import settings
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.bot import (
    BotCreate,
    BotOut,
    BotStepOut,
    BotTelegramStatusOut,
    BotUpdate,
    BotWebhookOut,
)
from app.services.telegram_sender import TelegramSenderService


DEFAULT_PROJECT_NAME = "Default Project"
DEFAULT_PROJECT_SLUG = "default-project"

logger = logging.getLogger(__name__)

TELEGRAM_WEBHOOK_ALLOWED_UPDATES = ("message", "callback_query")


class BotService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.project_repo = ProjectRepository(db)
        self.telegram_sender = TelegramSenderService(db)

    async def list_bots(
        self,
        project_id: Optional[UUID],
        limit: int,
        offset: int,
        actor: User | None = None,
    ) -> tuple[list[BotOut], int]:
        project_id = self._resolve_project_scope(actor, project_id)

        if project_id is None:
            bots = await self.bot_repo.list_active(limit=limit, offset=offset)
            total = await self.bot_repo.count_active()
            return [BotOut.model_validate(bot) for bot in bots], total

        await self._get_active_project_or_404(project_id)
        bots = await self.bot_repo.list_by_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        total = await self.bot_repo.count_by_project(project_id)
        return [BotOut.model_validate(bot) for bot in bots], total

    async def get_bot(self, bot_id: UUID, project_id: UUID) -> BotOut:
        bot = await self._get_bot_or_404(bot_id, project_id)
        return BotOut.model_validate(bot)

    async def create_bot(
        self,
        project_id: Optional[UUID],
        data: BotCreate,
    ) -> BotOut:
        project = await self._resolve_project_for_create(data.project_id or project_id)
        token = self._normalize_required(data.telegram_token, "telegram_token")
        telegram_info = await self._fetch_telegram_bot_info(token)
        identity_values = self._identity_values_from_get_me(telegram_info)
        name = (
            self._normalize_optional(data.name)
            or identity_values.get("telegram_first_name")
            or (
                f"@{identity_values['bot_username']}"
                if identity_values.get("bot_username")
                else None
            )
            or "Telegram bot"
        )

        bot = await self.bot_repo.create(
            project_id=project.id,
            name=name,
            telegram_token=token,
            **identity_values,
        )
        await self._set_webhook_for_token(token=token, bot_id=bot.id)
        return await self.get_bot(bot_id=bot.id, project_id=project.id)

    async def update_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
        data: BotUpdate,
    ) -> BotOut:
        bot = await self._get_bot_or_404(bot_id, project_id)
        values = data.model_dump(exclude_unset=True)

        if "name" in values:
            values["name"] = self._normalize_required(values["name"], "name")
        values.pop("bot_username", None)
        if "telegram_token" in values and values["telegram_token"] is None:
            values.pop("telegram_token")

        new_token: Optional[str] = None
        old_token: Optional[str] = None
        if "telegram_token" in values:
            new_token = self._normalize_required(values["telegram_token"], "telegram_token")
            old_token = self._normalize_optional(bot.telegram_token)
            telegram_info = await self._fetch_telegram_bot_info(new_token)
            identity_values = self._identity_values_from_get_me(telegram_info)
            await self._set_webhook_for_token(token=new_token, bot_id=bot_id)
            values["telegram_token"] = new_token
            values.update(identity_values)
            if "name" not in values:
                values["name"] = (
                    identity_values.get("telegram_first_name")
                    or (
                        f"@{identity_values['bot_username']}"
                        if identity_values.get("bot_username")
                        else None
                    )
                    or bot.name
                )

        if not values:
            return BotOut.model_validate(bot)

        updated = await self.bot_repo.update_in_project(bot_id, project_id, **values)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

        if new_token and old_token and old_token != new_token:
            await self._delete_webhook_safely(old_token)
            return await self.get_bot(bot_id=bot_id, project_id=project_id)

        return BotOut.model_validate(updated)

    async def delete_bot(self, bot_id: UUID, project_id: UUID) -> None:
        deleted = await self.bot_repo.soft_delete_from_project(bot_id, project_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

    async def list_bot_steps(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> list[BotStepOut]:
        bot = await self._get_bot_or_404(bot_id, project_id)
        steps = await self.bot_repo.list_steps_for_bot(bot.id, project_id)
        return [BotStepOut.model_validate(step) for step in steps]

    async def set_webhook(self, bot_id: UUID, project_id: UUID) -> BotWebhookOut:
        bot = await self._get_bot_or_404(bot_id, project_id)
        token = self._normalize_optional(bot.telegram_token)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot telegram_token is required to set webhook",
            )

        telegram_info = await self._fetch_telegram_bot_info(token)
        payload, webhook_url = await self._set_webhook_for_token(
            token=token,
            bot_id=bot.id,
        )
        identity_values = self._identity_values_from_get_me(telegram_info)
        identity_values["name"] = (
            identity_values.get("telegram_first_name")
            or (
                f"@{identity_values['bot_username']}"
                if identity_values.get("bot_username")
                else None
            )
            or bot.name
        )
        await self.bot_repo.update_in_project(bot.id, project_id, **identity_values)
        return BotWebhookOut(
            ok=True,
            webhook_url=webhook_url,
            telegram_response=payload,
        )

    async def sync_bot_identity_from_token(self, bot_id: UUID, project_id: UUID) -> BotOut:
        bot = await self._get_bot_or_404(bot_id, project_id)
        token = self._normalize_optional(bot.telegram_token)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot telegram_token is required to sync identity",
            )

        telegram_info = await self._fetch_telegram_bot_info(token)
        await self._set_webhook_for_token(token=token, bot_id=bot.id)
        identity_values = self._identity_values_from_get_me(telegram_info)
        identity_values["name"] = (
            identity_values.get("telegram_first_name")
            or (
                f"@{identity_values['bot_username']}"
                if identity_values.get("bot_username")
                else None
            )
            or bot.name
        )
        updated = await self.bot_repo.update_in_project(bot_id, project_id, **identity_values)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        return BotOut.model_validate(updated)

    async def telegram_status(self, bot_id: UUID, project_id: UUID) -> BotTelegramStatusOut:
        bot = await self._get_bot_or_404(bot_id, project_id)
        token = self._normalize_optional(bot.telegram_token)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot telegram_token is required to check Telegram status",
            )

        get_me = await self._fetch_telegram_bot_info(token)
        try:
            webhook_info = await self.telegram_sender.get_webhook_info(token)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram getWebhookInfo request failed: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram returned a non-JSON response",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        expected_webhook_url = self._webhook_url_for_bot(bot.id)
        identity_values = self._identity_values_from_get_me(get_me)
        identity_matches = (
            bot.telegram_bot_id == identity_values.get("telegram_bot_id")
            and bot.bot_username == identity_values.get("bot_username")
            and bot.telegram_first_name == identity_values.get("telegram_first_name")
        )
        return BotTelegramStatusOut(
            bot_id=bot.id,
            project_id=project_id,
            telegram_bot_id=bot.telegram_bot_id,
            bot_username=bot.bot_username,
            telegram_first_name=bot.telegram_first_name,
            get_me=get_me,
            webhook_info=webhook_info,
            identity_matches_crm=identity_matches,
            expected_webhook_url=expected_webhook_url,
            webhook_matches_expected=webhook_info.get("url") == expected_webhook_url,
        )

    async def ensure_bot_username(self, bot_id: UUID, project_id: UUID):
        bot = await self._get_bot_or_404(bot_id, project_id)
        if bot.bot_username:
            return bot

        token = self._normalize_optional(bot.telegram_token)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot username is missing and telegram_token is not configured",
            )

        telegram_info = await self._fetch_telegram_bot_info(token)
        identity_values = self._identity_values_from_get_me(telegram_info)
        if not identity_values.get("bot_username"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not resolve bot username from Telegram",
            )

        bot = await self.bot_repo.update_in_project(
            bot_id,
            project_id,
            **identity_values,
        )
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        return bot

    async def _get_bot_or_404(self, bot_id: UUID, project_id: UUID):
        bot = await self.bot_repo.get_by_id_and_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        return bot

    async def _resolve_project_for_create(self, project_id: Optional[UUID]):
        if project_id is None:
            # Temporary backwards compatibility for legacy callers that create
            # bots without a project_id. New API clients should pass or select
            # an explicit project.
            return await self._get_or_create_default_project()
        return await self._get_active_project_or_404(project_id)

    @staticmethod
    def _resolve_project_scope(
        actor: User | None,
        requested_project_id: UUID | None,
    ) -> UUID | None:
        if actor is None:
            return requested_project_id

        if actor.role_name == RoleName.SUPER_ADMIN:
            return requested_project_id

        if actor.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with a project",
            )

        if requested_project_id is not None and requested_project_id != actor.project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project is not accessible for current user",
            )

        return actor.project_id

    async def _get_active_project_or_404(self, project_id: UUID):
        project = await self.project_repo.get_any_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        if project.is_deleted or project.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project is archived",
            )
        return project

    async def _get_or_create_default_project(self):
        project = await self.project_repo.get_any_by_slug(DEFAULT_PROJECT_SLUG)
        if project is not None:
            if project.is_deleted or project.status == "archived":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Default project is archived",
                )
            return project

        return await self.project_repo.create(
            name=DEFAULT_PROJECT_NAME,
            slug=DEFAULT_PROJECT_SLUG,
            status="active",
            sla_threshold_minutes=30,
        )

    async def _set_webhook_for_token(self, *, token: str, bot_id: UUID) -> tuple[dict, str]:
        webhook_url = self._webhook_url_for_bot(bot_id)
        try:
            payload = await self.telegram_sender.set_webhook(
                token=token,
                webhook_url=webhook_url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                allowed_updates=TELEGRAM_WEBHOOK_ALLOWED_UPDATES,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram setWebhook request failed: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram returned a non-JSON response",
            ) from exc
        except RuntimeError as exc:
            if self._is_invalid_token_error(str(exc)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Telegram token is invalid: {exc}",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        return payload, webhook_url

    def _webhook_url_for_bot(self, bot_id: UUID) -> str:
        base_url = self._normalize_optional(settings.BASE_URL)
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="BASE_URL is not configured",
            )

        return f"{base_url.rstrip('/')}/api/v1/telegram/webhook/{bot_id}"

    async def _delete_webhook_safely(self, token: str) -> None:
        try:
            await self.telegram_sender.delete_webhook(token)
        except Exception:
            logger.warning("Could not delete old Telegram webhook", exc_info=True)

    async def _fetch_telegram_bot_info(self, token: str) -> dict[str, Any]:
        try:
            return await self.telegram_sender.get_me(token)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram getMe request failed: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram returned a non-JSON response",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Telegram token is invalid: {exc}",
            ) from exc

    @classmethod
    def _identity_values_from_get_me(cls, telegram_info: dict[str, Any]) -> dict[str, Any]:
        username = cls._normalize_username(telegram_info.get("username"))
        first_name = cls._normalize_optional(telegram_info.get("first_name"))
        telegram_bot_id = telegram_info.get("id")
        return {
            "telegram_bot_id": int(telegram_bot_id) if telegram_bot_id is not None else None,
            "telegram_first_name": first_name,
            "bot_username": username,
        }

    @staticmethod
    def _is_invalid_token_error(message: str) -> bool:
        normalized = message.strip().lower()
        return "not found" in normalized or "unauthorized" in normalized

    @staticmethod
    def _normalize_required(value: str | None, field_name: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must not be empty",
            )
        return normalized

    @staticmethod
    def _normalize_optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @classmethod
    def _normalize_username(cls, value: str | None) -> str | None:
        normalized = cls._normalize_optional(value)
        if normalized is None:
            return None
        return normalized.removeprefix("@")
