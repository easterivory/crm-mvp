from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telegram_commands import (
    MAX_TELEGRAM_COMMANDS,
    TELEGRAM_COMMAND_RE,
    collect_funnel_telegram_commands,
    normalize_telegram_command,
)
from app.repositories.bot_repository import BotRepository
from app.repositories.funnel_repository import FunnelRepository
from app.services.telegram_sender import TelegramSenderService


logger = logging.getLogger(__name__)


class FunnelCommandService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.funnel_repo = FunnelRepository(db)
        self.sender = TelegramSenderService(db)

    async def sync_for_bot(self, *, bot_id: UUID, project_id: UUID) -> bool:
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            return False
        token = str(bot.telegram_token or "").strip()
        if not token:
            logger.info(
                "Telegram command sync deferred until token is configured bot_id=%s",
                bot_id,
            )
            return False

        _, version = await self.funnel_repo.get_active_published_funnel_for_bot(
            bot_id,
            project_id,
        )
        steps = await self.funnel_repo.list_steps(version.id) if version is not None else []
        custom_commands = collect_funnel_telegram_commands(steps)
        managed_commands = [
            {"command": "start", "description": "Запустить бота"},
            *[
                {
                    "command": definition.command,
                    "description": definition.description,
                }
                for definition in custom_commands
                if definition.command != "start"
            ],
        ]
        managed_names = {item["command"] for item in managed_commands}
        previously_managed = {
            normalized
            for value in (getattr(bot, "telegram_managed_commands", None) or [])
            if (normalized := normalize_telegram_command(value))
        }
        existing_commands = await self.sender.get_bot_commands(token)
        preserved_commands: list[dict[str, str]] = []
        seen = set(managed_names)
        for item in existing_commands:
            command = normalize_telegram_command(item.get("command"))
            description = str(item.get("description") or "").strip()
            if (
                not TELEGRAM_COMMAND_RE.fullmatch(command)
                or not description
                or command in seen
                or command in previously_managed
            ):
                continue
            preserved_commands.append(
                {"command": command, "description": description[:256]}
            )
            seen.add(command)

        commands = [*managed_commands, *preserved_commands]
        if len(commands) > MAX_TELEGRAM_COMMANDS:
            raise RuntimeError(
                "Telegram command menu is full; remove an existing BotFather command "
                "before adding funnel commands"
            )
        await self.sender.set_bot_commands(token, commands)
        await self.bot_repo.update_in_project(
            bot_id,
            project_id,
            telegram_managed_commands=sorted(managed_names),
        )
        await self.db.commit()
        logger.info(
            "Telegram command menu synchronized bot_id=%s managed=%s preserved=%s",
            bot_id,
            sorted(managed_names),
            [item["command"] for item in preserved_commands],
        )
        return True

    async def sync_for_bot_safely(self, *, bot_id: UUID, project_id: UUID) -> bool:
        try:
            return await self.sync_for_bot(bot_id=bot_id, project_id=project_id)
        except Exception:
            try:
                await self.db.rollback()
            except Exception:
                logger.exception(
                    "Telegram command sync rollback failed bot_id=%s project_id=%s",
                    bot_id,
                    project_id,
                )
            logger.warning(
                "Telegram command menu sync failed bot_id=%s project_id=%s",
                bot_id,
                project_id,
                exc_info=True,
            )
            return False
