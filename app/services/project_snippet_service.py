from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.project_snippet import ProjectSnippet
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_snippet_repository import ProjectSnippetRepository
from app.schemas.snippet import SnippetCreate, SnippetOut
from app.services.access_control import require_project_access

logger = logging.getLogger(__name__)


class ProjectSnippetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.snippet_repo = ProjectSnippetRepository(db)

    async def list_snippets(self, *, project_id: UUID, actor: User) -> list[SnippetOut]:
        await self._ensure_access(project_id, actor)
        snippets = await self.snippet_repo.list_by_project(project_id)
        return [SnippetOut.model_validate(snippet) for snippet in snippets]

    async def create_snippet(
        self,
        *,
        project_id: UUID,
        actor: User,
        data: SnippetCreate,
    ) -> SnippetOut:
        await self._ensure_access(project_id, actor)
        self._ensure_can_manage(actor)
        snippet = await self.snippet_repo.create_in_project(
            project_id=project_id,
            channel=data.channel,
            name=data.name,
            snippet_type=data.type,
            content=data.content,
            file_id=data.file_id,
        )
        logger.info("Project snippet created project_id=%s snippet_id=%s actor_id=%s", project_id, snippet.id, actor.id)
        return SnippetOut.model_validate(snippet)

    async def delete_snippet(
        self,
        *,
        project_id: UUID,
        snippet_id: UUID,
        actor: User,
    ) -> None:
        await self._ensure_access(project_id, actor)
        self._ensure_can_manage(actor)
        deleted = await self.snippet_repo.delete_in_project(snippet_id, project_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
        logger.info("Project snippet deleted project_id=%s snippet_id=%s actor_id=%s", project_id, snippet_id, actor.id)

    async def get_snippet_for_send(
        self,
        *,
        project_id: UUID,
        snippet_id: UUID,
        actor: User,
    ) -> ProjectSnippet:
        await self._ensure_access(project_id, actor)
        snippet = await self.snippet_repo.get_in_project(snippet_id, project_id)
        if snippet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
        return snippet

    async def _ensure_access(self, project_id: UUID, actor: User) -> None:
        require_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    @staticmethod
    def _ensure_can_manage(actor: User) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can manage project snippets",
            )
