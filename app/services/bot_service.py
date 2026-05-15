"""
BotService - project-scoped Telegram bot management.
"""
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.bot_repository import BotRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.bot import BotCreate, BotOut, BotStepOut, BotUpdate, BotWebhookOut
from app.services.telegram_sender import TelegramSenderService


DEFAULT_PROJECT_NAME = "Default Project"
DEFAULT_PROJECT_SLUG = "default-project"


class BotService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.project_repo = ProjectRepository(db)

    async def list_bots(
        self,
        project_id: Optional[UUID],
        limit: int,
        offset: int,
    ) -> tuple[list[BotOut], int]:
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
        username = self._normalize_username(data.bot_username)
        telegram_info = await self._fetch_telegram_bot_info(token) if not username else None

        username = username or self._normalize_username(
            telegram_info.get("username") if telegram_info else None
        )
        name = self._normalize_optional(data.name)
        if not name and telegram_info:
            name = self._normalize_optional(telegram_info.get("first_name"))
        name = name or (f"@{username}" if username else "Telegram bot")

        bot = await self.bot_repo.create(
            project_id=project.id,
            name=name,
            telegram_token=token,
            bot_username=username,
        )
        await self.set_webhook(bot_id=bot.id, project_id=project.id)
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
        if "telegram_token" in values and values["telegram_token"] is not None:
            values["telegram_token"] = self._normalize_required(
                values["telegram_token"], "telegram_token"
            )
        if "bot_username" in values:
            values["bot_username"] = self._normalize_username(values["bot_username"])

        if (
            "telegram_token" in values
            and values["telegram_token"]
            and "bot_username" not in values
        ):
            telegram_info = await self._fetch_telegram_bot_info(values["telegram_token"])
            username = self._normalize_username(
                telegram_info.get("username") if telegram_info else None
            )
            if username:
                values["bot_username"] = username
            if "name" not in values and telegram_info:
                first_name = self._normalize_optional(telegram_info.get("first_name"))
                if first_name and bot.name == "Telegram bot":
                    values["name"] = first_name

        should_refresh_webhook = "telegram_token" in values and bool(
            values["telegram_token"]
        )

        if not values:
            return BotOut.model_validate(bot)

        updated = await self.bot_repo.update_in_project(bot_id, project_id, **values)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

        if should_refresh_webhook:
            await self.set_webhook(bot_id=bot_id, project_id=project_id)
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

        base_url = self._normalize_optional(settings.BASE_URL)
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="BASE_URL is not configured",
            )

        webhook_url = f"{base_url.rstrip('/')}/api/v1/telegram/webhook/{bot.id}"

        try:
            payload = await TelegramSenderService(self.db).set_webhook(
                token=token,
                webhook_url=webhook_url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
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
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        await self.ensure_bot_username(bot_id=bot.id, project_id=project_id)
        return BotWebhookOut(
            ok=True,
            webhook_url=webhook_url,
            telegram_response=payload,
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
        username = self._normalize_username(
            telegram_info.get("username") if telegram_info else None
        )
        if not username:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not resolve bot username from Telegram",
            )

        bot = await self.bot_repo.update_in_project(
            bot_id,
            project_id,
            bot_username=username,
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

    @staticmethod
    async def _fetch_telegram_bot_info(token: str) -> Optional[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        if response.status_code >= 400 or payload.get("ok") is not True:
            return None

        result = payload.get("result")
        return result if isinstance(result, dict) else None

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
