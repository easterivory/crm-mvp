from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.bot import Bot, TelegramUserConnection
from app.repositories.base import BaseRepository


class TelegramUserConnectionRepository(BaseRepository[TelegramUserConnection]):
    model = TelegramUserConnection

    async def get_by_bot_id(
        self,
        bot_id: UUID,
        *,
        for_update: bool = False,
    ) -> TelegramUserConnection | None:
        statement = select(TelegramUserConnection).where(
            TelegramUserConnection.bot_id == bot_id
        ).options(selectinload(TelegramUserConnection.bot))
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list_authorized(self) -> list[TelegramUserConnection]:
        result = await self.db.execute(
            select(TelegramUserConnection)
            .options(selectinload(TelegramUserConnection.bot))
            .join(Bot, Bot.id == TelegramUserConnection.bot_id)
            .where(
                TelegramUserConnection.auth_status == "authorized",
                TelegramUserConnection.session_encrypted.is_not(None),
                Bot.transport_type == "user_mtproto",
                Bot.is_deleted.is_(False),
            )
            .order_by(TelegramUserConnection.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_by_bot_id(
        self,
        bot_id: UUID,
        **values: Any,
    ) -> TelegramUserConnection | None:
        values["updated_at"] = datetime.now(timezone.utc)
        await self.db.execute(
            update(TelegramUserConnection)
            .where(TelegramUserConnection.bot_id == bot_id)
            .values(**values)
        )
        return await self.get_by_bot_id(bot_id)

    async def delete_by_bot_id(self, bot_id: UUID) -> bool:
        connection = await self.get_by_bot_id(bot_id)
        if connection is None:
            return False
        await self.db.delete(connection)
        await self.db.flush()
        return True
