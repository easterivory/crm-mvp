from typing import Optional
from uuid import UUID

from sqlalchemy import delete, or_, select, update

from app.models.chat_filter_preset import ChatFilterPreset
from app.repositories.base import BaseRepository


class ChatFilterPresetRepository(BaseRepository[ChatFilterPreset]):
    model = ChatFilterPreset

    async def list_visible(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
    ) -> list[ChatFilterPreset]:
        result = await self.db.execute(
            select(ChatFilterPreset)
            .where(
                ChatFilterPreset.project_id == project_id,
                or_(
                    ChatFilterPreset.user_id == user_id,
                    ChatFilterPreset.is_shared.is_(True),
                ),
            )
            .order_by(
                ChatFilterPreset.is_shared.desc(),
                ChatFilterPreset.name.asc(),
                ChatFilterPreset.created_at.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_in_project(
        self,
        *,
        preset_id: UUID,
        project_id: UUID,
    ) -> Optional[ChatFilterPreset]:
        result = await self.db.execute(
            select(ChatFilterPreset).where(
                ChatFilterPreset.id == preset_id,
                ChatFilterPreset.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_preset(
        self,
        *,
        preset_id: UUID,
        values: dict,
    ) -> Optional[ChatFilterPreset]:
        await self.db.execute(
            update(ChatFilterPreset)
            .where(ChatFilterPreset.id == preset_id)
            .values(**values)
        )
        return await self.get_by_id(preset_id)

    async def delete_preset(self, preset_id: UUID) -> bool:
        result = await self.db.execute(
            delete(ChatFilterPreset).where(ChatFilterPreset.id == preset_id)
        )
        return result.rowcount > 0
