from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select

from app.models.project_snippet import ProjectSnippet
from app.repositories.base import BaseRepository


class ProjectSnippetRepository(BaseRepository[ProjectSnippet]):
    model = ProjectSnippet

    async def list_by_project(self, project_id: UUID) -> list[ProjectSnippet]:
        result = await self.db.execute(
            select(ProjectSnippet)
            .where(ProjectSnippet.project_id == project_id)
            .order_by(ProjectSnippet.created_at.desc(), ProjectSnippet.name.asc())
        )
        return list(result.scalars().all())

    async def get_in_project(
        self,
        snippet_id: UUID,
        project_id: UUID,
    ) -> Optional[ProjectSnippet]:
        result = await self.db.execute(
            select(ProjectSnippet).where(
                ProjectSnippet.id == snippet_id,
                ProjectSnippet.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_in_project(
        self,
        *,
        project_id: UUID,
        channel: str,
        name: str,
        snippet_type: str,
        content: str | None,
        file_id: str | None,
        storage_path: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
    ) -> ProjectSnippet:
        return await self.create(
            project_id=project_id,
            channel=channel,
            name=name,
            type=snippet_type,
            content=content,
            file_id=file_id,
            storage_path=storage_path,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
        )

    async def delete_in_project(self, snippet_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            delete(ProjectSnippet).where(
                ProjectSnippet.id == snippet_id,
                ProjectSnippet.project_id == project_id,
            )
        )
        return bool(result.rowcount)
