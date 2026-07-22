"""
BotService - project-scoped Telegram bot management.
"""
import csv
import io
import logging
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName, TELEGRAM_WEBHOOK_ALLOWED_UPDATES
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
from app.services.access_control import resolve_scoped_project_id
from app.services.funnel_command_service import FunnelCommandService
from app.services.telegram_bot_avatar_service import (
    BotAvatarUnavailableError,
    TelegramBotAvatarService,
)
from app.services.telegram_sender import TelegramSenderService


DEFAULT_PROJECT_NAME = "Default Project"
DEFAULT_PROJECT_SLUG = "default-project"

logger = logging.getLogger(__name__)

class BotService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.project_repo = ProjectRepository(db)
        self.telegram_sender = TelegramSenderService(db)
        self.avatar_service = TelegramBotAvatarService(sender=self.telegram_sender)
        self.funnel_commands = FunnelCommandService(db)

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
        token = self._normalize_optional(data.telegram_token)
        identity_values: dict[str, Any] = {}
        if token is not None:
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
        )
        if name is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Укажите название черновика или Telegram token",
            )

        bot = await self.bot_repo.create(
            project_id=project.id,
            name=name,
            telegram_token=token,
            **identity_values,
            **self._bot_profile_values(data),
        )
        if token is not None:
            await self._set_webhook_for_token(token=token, bot_id=bot.id)
            await self._sync_funnel_commands_after_commit(
                bot_id=bot.id,
                project_id=project.id,
            )
        return await self.get_bot(bot_id=bot.id, project_id=project.id)

    async def update_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
        data: BotUpdate,
        actor: User | None = None,
    ) -> BotOut:
        bot = await self._get_bot_or_404(bot_id, project_id)
        values = data.model_dump(exclude_unset=True)

        if "name" in values:
            values["name"] = self._normalize_required(values["name"], "name")
        for field_name in ("crm_description", "telegram_description", "telegram_about"):
            if field_name in values:
                values[field_name] = self._normalize_optional(values[field_name])
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

        previous_values = self._bot_snapshot(bot)
        updated = await self.bot_repo.update_in_project(bot_id, project_id, **values)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        if actor is not None:
            await self._log_bot_setting_updates(
                bot_id=bot_id,
                actor=actor,
                previous_values=previous_values,
                values=values,
            )

        if new_token is not None:
            await self.avatar_service.invalidate(bot_id)
            await self._sync_funnel_commands_after_commit(
                bot_id=bot_id,
                project_id=project_id,
            )

        if new_token and old_token and old_token != new_token:
            await self._delete_webhook_safely(old_token)
            return await self.get_bot(bot_id=bot_id, project_id=project_id)

        return BotOut.model_validate(updated)

    async def update_bot_profile_on_telegram(
        self,
        bot_id: UUID,
        actor: User | None = None,
    ) -> dict[str, Any]:
        bot = await self._get_active_bot_or_404(bot_id)
        token = self._normalize_optional(bot.telegram_token)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot telegram_token is required to update Telegram profile",
            )

        self._validate_bot_profile_texts(bot.telegram_description, bot.telegram_about)
        responses: dict[str, Any] = {}
        try:
            responses["setMyDescription"] = await self.telegram_sender.set_bot_description(
                token,
                bot.telegram_description,
            )
            responses["setMyShortDescription"] = await self.telegram_sender.set_bot_about_text(
                token,
                bot.telegram_about,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram bot profile request failed: {exc}",
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
        if actor is not None:
            await self.log_bot_config_change(
                bot_id=bot_id,
                user_id=actor.id,
                action_type="update_settings",
                description="Оператор синхронизировал описание Telegram-бота.",
            )
        return responses

    async def set_bot_profile_photo(
        self,
        bot_id: UUID,
        photo_bytes: bytes,
        *,
        actor: User | None = None,
        file_name: str = "bot_profile.jpg",
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        bot = await self._get_active_bot_or_404(bot_id)
        token = self._normalize_optional(bot.telegram_token)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot telegram_token is required to update Telegram profile photo",
            )

        try:
            payload = await self.telegram_sender.set_bot_profile_photo(
                token,
                photo_bytes,
                file_name=file_name,
                mime_type=mime_type,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram setMyProfilePhoto request failed: {exc}",
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

        await self.avatar_service.invalidate(bot_id)

        if actor is not None:
            await self.log_bot_config_change(
                bot_id=bot_id,
                user_id=actor.id,
                action_type="avatar_changed",
                description="Оператор обновил аватар Telegram-бота.",
            )
        return payload

    async def get_bot_profile_photo(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
    ) -> tuple[bytes, str]:
        bot = await self._get_bot_or_404(bot_id, project_id)
        token = self._normalize_optional(bot.telegram_token)
        telegram_bot_id = bot.telegram_bot_id
        if not token or telegram_bot_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bot profile photo is unavailable",
            )
        if self.db.in_transaction():
            await self.db.commit()
        try:
            return await self.avatar_service.get_avatar(
                bot_id=bot.id,
                token=token,
                telegram_bot_id=telegram_bot_id,
            )
        except BotAvatarUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bot profile photo is unavailable",
            ) from exc

    async def export_bot_audit_logs_to_csv(self, bot_id: UUID) -> bytes:
        await self._get_active_bot_or_404(bot_id)
        logs = await self.bot_repo.list_config_audit_logs(bot_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Дата", "Оператор", "Действие", "Детали"])
        for log in logs:
            operator = "Система"
            if log.user is not None:
                operator = log.user.name or log.user.email
            writer.writerow(
                [
                    log.created_at.isoformat(),
                    operator,
                    log.action_type,
                    log.description,
                ]
            )
        return output.getvalue().encode("utf-8-sig")

    async def log_bot_config_change(
        self,
        *,
        bot_id: UUID,
        user_id: UUID | None,
        action_type: str,
        description: str,
    ) -> None:
        action = self._normalize_required(action_type, "action_type")
        details = self._normalize_required(description, "description")
        await self.bot_repo.create_config_audit_log(
            bot_id=bot_id,
            user_id=user_id,
            action_type=action,
            description=details,
        )

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
        await self._sync_funnel_commands_after_commit(
            bot_id=bot.id,
            project_id=project_id,
        )
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
        await self._sync_funnel_commands_after_commit(
            bot_id=bot_id,
            project_id=project_id,
        )
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

    async def _get_active_bot_or_404(self, bot_id: UUID):
        bot = await self.bot_repo.get_active(bot_id)
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

        return resolve_scoped_project_id(actor, requested_project_id)

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

    async def _sync_funnel_commands_after_commit(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        await self.db.commit()
        await self.funnel_commands.sync_for_bot_safely(
            bot_id=bot_id,
            project_id=project_id,
        )

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
    def _bot_profile_values(data: BotCreate) -> dict[str, str | None]:
        return {
            "crm_description": BotService._normalize_optional(data.crm_description),
            "telegram_description": BotService._normalize_optional(data.telegram_description),
            "telegram_about": BotService._normalize_optional(data.telegram_about),
        }

    async def _log_bot_setting_updates(
        self,
        *,
        bot_id: UUID,
        actor: User,
        previous_values: dict[str, str | None],
        values: dict[str, Any],
    ) -> None:
        descriptions: list[str] = []
        if "name" in values and self._changed(previous_values.get("name"), values["name"]):
            descriptions.append(f"Оператор изменил имя бота на: {values['name']}")
        if "telegram_token" in values:
            descriptions.append("Оператор обновил Telegram token бота.")
        if "crm_description" in values and self._changed(previous_values.get("crm_description"), values["crm_description"]):
            descriptions.append("Оператор обновил CRM-описание бота.")
        if "telegram_description" in values and self._changed(
            previous_values.get("telegram_description"),
            values["telegram_description"],
        ):
            descriptions.append("Оператор обновил приветственное описание Telegram-бота.")
        if "telegram_about" in values and self._changed(previous_values.get("telegram_about"), values["telegram_about"]):
            descriptions.append("Оператор обновил текст «О боте» в Telegram.")

        for description in descriptions:
            await self.log_bot_config_change(
                bot_id=bot_id,
                user_id=actor.id,
                action_type="update_settings",
                description=description,
            )

    @staticmethod
    def _validate_bot_profile_texts(
        telegram_description: str | None,
        telegram_about: str | None,
    ) -> None:
        if telegram_description is not None and len(telegram_description) > 512:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="telegram_description must not exceed 512 characters",
            )
        if telegram_about is not None and len(telegram_about) > 120:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="telegram_about must not exceed 120 characters",
            )

    @staticmethod
    def _changed(left: str | None, right: str | None) -> bool:
        return (left or "") != (right or "")

    @staticmethod
    def _bot_snapshot(bot) -> dict[str, str | None]:
        return {
            "name": bot.name,
            "crm_description": bot.crm_description,
            "telegram_description": bot.telegram_description,
            "telegram_about": bot.telegram_about,
        }

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
