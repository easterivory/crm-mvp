"""
Bot repository.

State-machine services use this repository to load bot execution state and
steps, and to persist the current pointer and collected variables.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update

from app.models.bot import Bot, BotStep, BotVersion, ChatBotState
from app.repositories.base import BaseRepository


class BotRepository(BaseRepository[Bot]):
    model = Bot

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Bot]:
        result = await self.db.execute(
            select(Bot)
            .where(Bot.project_id == project_id, Bot.is_deleted.is_(False))
            .order_by(Bot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Bot.id)).where(
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
        )
        return result.scalar_one()

    async def get_by_id_in_project(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> Optional[Bot]:
        result = await self.db.execute(
            select(Bot).where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_active(self, bot_id: UUID) -> Optional[Bot]:
        result = await self.db.execute(
            select(Bot).where(
                Bot.id == bot_id,
                Bot.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def update_in_project(
        self,
        bot_id: UUID,
        project_id: UUID,
        **values: Any,
    ) -> Optional[Bot]:
        await self.db.execute(
            update(Bot)
            .where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
            .values(**values)
        )
        return await self.get_by_id_in_project(bot_id, project_id)

    async def soft_delete_from_project(self, bot_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            update(Bot)
            .where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        return result.rowcount > 0

    async def get_chat_state(self, chat_id: UUID) -> Optional[ChatBotState]:
        result = await self.db.execute(
            select(ChatBotState)
            .where(ChatBotState.chat_id == chat_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_step(self, step_id: UUID) -> Optional[BotStep]:
        result = await self.db.execute(select(BotStep).where(BotStep.id == step_id))
        return result.scalar_one_or_none()

    async def get_active_version_for_project(
        self,
        project_id: UUID,
    ) -> Optional[BotVersion]:
        result = await self.db.execute(
            select(BotVersion)
            .join(Bot, Bot.id == BotVersion.bot_id)
            .where(
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
                BotVersion.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_version_for_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> Optional[BotVersion]:
        result = await self.db.execute(
            select(BotVersion)
            .join(Bot, Bot.id == BotVersion.bot_id)
            .where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
                BotVersion.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_steps_for_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> list[BotStep]:
        active_version = await self.get_active_version_for_bot(bot_id, project_id)
        if active_version is None:
            return []

        result = await self.db.execute(
            select(BotStep)
            .where(BotStep.bot_version_id == active_version.id)
            .order_by(BotStep.created_at.asc())
        )
        return list(result.scalars().all())

    async def step_belongs_to_bot(
        self,
        step_id: UUID,
        bot_id: UUID,
        project_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            select(BotStep.id)
            .join(BotVersion, BotVersion.id == BotStep.bot_version_id)
            .join(Bot, Bot.id == BotVersion.bot_id)
            .where(
                BotStep.id == step_id,
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def step_belongs_to_version(
        self,
        step_id: UUID,
        bot_version_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            select(BotStep.id)
            .where(
                BotStep.id == step_id,
                BotStep.bot_version_id == bot_version_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_active_bot_token(self, project_id: UUID) -> Optional[str]:
        result = await self.db.execute(
            select(Bot.telegram_token)
            .join(BotVersion, BotVersion.bot_id == Bot.id)
            .where(
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
                Bot.telegram_token.is_not(None),
                BotVersion.is_active.is_(True),
            )
            .limit(1)
        )
        token = result.scalar_one_or_none()
        return token.strip() if token else None

    async def get_bot_token_by_id(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> Optional[str]:
        result = await self.db.execute(
            select(Bot.telegram_token).where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
                Bot.telegram_token.is_not(None),
            )
        )
        token = result.scalar_one_or_none()
        return token.strip() if token else None

    async def get_project_id_for_bot_version(
        self,
        bot_version_id: UUID,
    ) -> Optional[UUID]:
        result = await self.db.execute(
            select(Bot.project_id)
            .join(BotVersion, BotVersion.bot_id == Bot.id)
            .where(BotVersion.id == bot_version_id, Bot.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def update_chat_state(
        self,
        *,
        chat_id: UUID,
        current_step_id: Optional[UUID],
        variables: dict[str, Any],
        last_interaction_at: Optional[datetime] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(ChatBotState)
            .where(ChatBotState.chat_id == chat_id)
            .values(
                current_step_id=current_step_id,
                variables=variables,
                last_interaction_at=last_interaction_at or now,
                updated_at=now,
            )
        )

    async def create_chat_state(
        self,
        *,
        chat_id: UUID,
        bot_version_id: UUID,
        current_step_id: Optional[UUID],
    ) -> ChatBotState:
        state = ChatBotState(
            chat_id=chat_id,
            bot_version_id=bot_version_id,
            current_step_id=current_step_id,
            variables={},
        )
        self.db.add(state)
        await self.db.flush()
        await self.db.refresh(state)
        return state

    async def disable_bot_for_chat(self, chat_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(ChatBotState)
            .where(ChatBotState.chat_id == chat_id)
            .values(is_active=False, updated_at=now)
        )
