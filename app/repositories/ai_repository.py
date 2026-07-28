from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update

from app.models.ai import AIProjectSettings, AIProviderConnection, AIUsageLog
from app.repositories.base import BaseRepository


class AIRepository:
    def __init__(self, db) -> None:
        self.db = db

    async def list_connections(self) -> list[AIProviderConnection]:
        result = await self.db.execute(
            select(AIProviderConnection)
            .where(AIProviderConnection.is_deleted.is_(False))
            .order_by(
                AIProviderConnection.is_active.desc(),
                AIProviderConnection.name.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_connection(
        self,
        connection_id: UUID,
        *,
        active_only: bool = False,
    ) -> Optional[AIProviderConnection]:
        stmt = select(AIProviderConnection).where(
            AIProviderConnection.id == connection_id,
            AIProviderConnection.is_deleted.is_(False),
        )
        if active_only:
            stmt = stmt.where(AIProviderConnection.is_active.is_(True))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_connection(self, **values: Any) -> AIProviderConnection:
        connection = AIProviderConnection(**values)
        self.db.add(connection)
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def update_connection(
        self,
        connection_id: UUID,
        **values: Any,
    ) -> Optional[AIProviderConnection]:
        values["updated_at"] = func.now()
        result = await self.db.execute(
            update(AIProviderConnection)
            .where(
                AIProviderConnection.id == connection_id,
                AIProviderConnection.is_deleted.is_(False),
            )
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_connection(connection_id)

    async def soft_delete_connection(self, connection_id: UUID) -> bool:
        result = await self.db.execute(
            update(AIProviderConnection)
            .where(
                AIProviderConnection.id == connection_id,
                AIProviderConnection.is_deleted.is_(False),
            )
            .values(
                is_deleted=True,
                is_active=False,
                encrypted_api_key=None,
                updated_at=func.now(),
            )
        )
        return result.rowcount == 1

    async def connection_used_by_enabled_project(
        self,
        connection_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            select(func.count(AIProjectSettings.project_id)).where(
                AIProjectSettings.is_enabled.is_(True),
                (
                    (AIProjectSettings.primary_connection_id == connection_id)
                    | (AIProjectSettings.fallback_connection_id == connection_id)
                ),
            )
        )
        return int(result.scalar_one() or 0) > 0

    async def get_project_settings(
        self,
        project_id: UUID,
    ) -> Optional[AIProjectSettings]:
        result = await self.db.execute(
            select(AIProjectSettings).where(
                AIProjectSettings.project_id == project_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert_project_settings(
        self,
        project_id: UUID,
        **values: Any,
    ) -> AIProjectSettings:
        current = await self.get_project_settings(project_id)
        if current is None:
            current = AIProjectSettings(project_id=project_id, **values)
            self.db.add(current)
            await self.db.flush()
            await self.db.refresh(current)
            return current
        values["updated_at"] = func.now()
        await self.db.execute(
            update(AIProjectSettings)
            .where(AIProjectSettings.project_id == project_id)
            .values(**values)
        )
        refreshed = await self.get_project_settings(project_id)
        assert refreshed is not None
        return refreshed

    async def create_usage_log(self, **values: Any) -> AIUsageLog:
        usage = AIUsageLog(**values)
        self.db.add(usage)
        await self.db.flush()
        await self.db.refresh(usage)
        return usage

    async def usage_cost_total(
        self,
        *,
        project_id: UUID,
        created_from: datetime,
    ) -> Decimal:
        result = await self.db.execute(
            select(func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0)).where(
                AIUsageLog.project_id == project_id,
                AIUsageLog.created_at >= created_from,
            )
        )
        return Decimal(result.scalar_one() or 0)

    async def list_usage(
        self,
        *,
        project_id: UUID,
        date_from: datetime,
        date_to: datetime,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[AIUsageLog, str | None]], int]:
        filters = (
            AIUsageLog.project_id == project_id,
            AIUsageLog.created_at >= date_from,
            AIUsageLog.created_at < date_to,
        )
        count_result = await self.db.execute(
            select(func.count(AIUsageLog.id)).where(*filters)
        )
        result = await self.db.execute(
            select(AIUsageLog, AIProviderConnection.name)
            .outerjoin(
                AIProviderConnection,
                AIProviderConnection.id == AIUsageLog.connection_id,
            )
            .where(*filters)
            .order_by(AIUsageLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            (row[0], row[1])
            for row in result.all()
        ], count_result.scalar_one()

    async def usage_summary(
        self,
        *,
        project_id: UUID,
        date_from: datetime,
        date_to: datetime,
    ) -> dict[str, Any]:
        filters = (
            AIUsageLog.project_id == project_id,
            AIUsageLog.created_at >= date_from,
            AIUsageLog.created_at < date_to,
        )
        result = await self.db.execute(
            select(
                func.count(AIUsageLog.id),
                func.count(AIUsageLog.id).filter(AIUsageLog.status == "success"),
                func.count(AIUsageLog.id).filter(AIUsageLog.status == "failed"),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0),
                func.count(AIUsageLog.id).filter(
                    AIUsageLog.estimated_cost_usd.is_(None)
                ),
                func.coalesce(func.avg(AIUsageLog.latency_ms), 0),
            ).where(*filters)
        )
        row = result.one()
        grouped_result = await self.db.execute(
            select(
                AIUsageLog.provider,
                AIUsageLog.model,
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0),
                func.count(AIUsageLog.id).filter(
                    AIUsageLog.estimated_cost_usd.is_(None)
                ),
            )
            .where(*filters)
            .group_by(AIUsageLog.provider, AIUsageLog.model)
            .order_by(func.count(AIUsageLog.id).desc())
        )
        connection_result = await self.db.execute(
            select(
                AIUsageLog.connection_id,
                AIUsageLog.credential_fingerprint,
                AIUsageLog.api_key_last_four,
                AIProviderConnection.name,
                AIUsageLog.provider,
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0),
                func.count(AIUsageLog.id).filter(
                    AIUsageLog.estimated_cost_usd.is_(None)
                ),
            )
            .outerjoin(
                AIProviderConnection,
                AIProviderConnection.id == AIUsageLog.connection_id,
            )
            .where(*filters)
            .group_by(
                AIUsageLog.connection_id,
                AIUsageLog.credential_fingerprint,
                AIUsageLog.api_key_last_four,
                AIProviderConnection.name,
                AIUsageLog.provider,
            )
            .order_by(func.count(AIUsageLog.id).desc())
        )
        return {
            "requests": int(row[0] or 0),
            "successful_requests": int(row[1] or 0),
            "failed_requests": int(row[2] or 0),
            "total_tokens": int(row[3] or 0),
            "estimated_cost_usd": Decimal(row[4] or 0),
            "unknown_cost_requests": int(row[5] or 0),
            "average_latency_ms": int(row[6] or 0),
            "by_model": [
                {
                    "provider": item[0],
                    "model": item[1],
                    "requests": int(item[2] or 0),
                    "total_tokens": int(item[3] or 0),
                    "estimated_cost_usd": Decimal(item[4] or 0),
                    "unknown_cost_requests": int(item[5] or 0),
                }
                for item in grouped_result.all()
            ],
            "by_connection": [
                {
                    "connection_id": item[0],
                    "connection_name": item[3] or f"{item[4]} (удалено)",
                    "provider": item[4],
                    "api_key_mask": (
                        f"••••{item[2]}"
                        if item[2]
                        else None
                    ),
                    "requests": int(item[5] or 0),
                    "total_tokens": int(item[6] or 0),
                    "estimated_cost_usd": Decimal(item[7] or 0),
                    "unknown_cost_requests": int(item[8] or 0),
                }
                for item in connection_result.all()
            ],
        }


class AIUsageRepository(BaseRepository[AIUsageLog]):
    model = AIUsageLog
