from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.core.config import settings
from app.models.project_snippet import ProjectSnippet
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_snippet_repository import ProjectSnippetRepository
from app.schemas.snippet import (
    TELEGRAM_CAPTION_LIMIT,
    TELEGRAM_TEXT_LIMIT,
    SnippetCreate,
    SnippetOut,
    SnippetUpdate,
)
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
        self._ensure_can_create(actor)
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

    async def create_uploaded_snippet(
        self,
        *,
        project_id: UUID,
        actor: User,
        name: str,
        snippet_type: str,
        content: str | None,
        file: UploadFile,
    ) -> SnippetOut:
        await self._ensure_access(project_id, actor)
        self._ensure_can_create(actor)
        normalized_name = self._normalize_name(name)
        normalized_content = self._normalize_media_content(content)
        stored_file = await self._store_upload(
            project_id=project_id,
            snippet_type=snippet_type,
            file=file,
        )
        try:
            snippet = await self.snippet_repo.create_in_project(
                project_id=project_id,
                channel="telegram",
                name=normalized_name,
                snippet_type=snippet_type,
                content=normalized_content,
                file_id=None,
                storage_path=str(stored_file[0]),
                file_name=stored_file[1],
                mime_type=stored_file[2],
                file_size=stored_file[3],
            )
        except Exception:
            stored_file[0].unlink(missing_ok=True)
            raise

        logger.info(
            "Project media snippet created project_id=%s snippet_id=%s actor_id=%s",
            project_id,
            snippet.id,
            actor.id,
        )
        return SnippetOut.model_validate(snippet)

    async def update_snippet(
        self,
        *,
        project_id: UUID,
        snippet_id: UUID,
        actor: User,
        data: SnippetUpdate,
    ) -> SnippetOut:
        await self._ensure_access(project_id, actor)
        self._ensure_can_update(actor)
        snippet = await self.snippet_repo.get_in_project(snippet_id, project_id)
        if snippet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")

        values = data.model_dump(exclude_unset=True)
        if "content" in values:
            if snippet.type == "text":
                normalized_content = str(values["content"] or "").strip()
                if not normalized_content:
                    raise HTTPException(status_code=422, detail="Text snippet requires content")
                if len(normalized_content) > TELEGRAM_TEXT_LIMIT:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Text snippet cannot exceed {TELEGRAM_TEXT_LIMIT} characters",
                    )
                values["content"] = normalized_content
            else:
                values["content"] = self._normalize_media_content(values["content"])

        updated = await self.snippet_repo.update_in_project(
            snippet_id,
            project_id,
            **values,
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
        logger.info(
            "Project snippet updated project_id=%s snippet_id=%s actor_id=%s",
            project_id,
            snippet_id,
            actor.id,
        )
        return SnippetOut.model_validate(updated)

    async def replace_uploaded_snippet(
        self,
        *,
        project_id: UUID,
        snippet_id: UUID,
        actor: User,
        name: str,
        snippet_type: str,
        content: str | None,
        file: UploadFile,
    ) -> SnippetOut:
        await self._ensure_access(project_id, actor)
        self._ensure_can_update(actor)
        snippet = await self.snippet_repo.get_in_project(snippet_id, project_id)
        if snippet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
        if snippet.type == "text":
            raise HTTPException(status_code=422, detail="Text snippets do not have media files")

        normalized_name = self._normalize_name(name)
        normalized_content = self._normalize_media_content(content)
        stored_file = await self._store_upload(
            project_id=project_id,
            snippet_type=snippet_type,
            file=file,
        )
        old_storage_path = Path(snippet.storage_path) if snippet.storage_path else None
        try:
            updated = await self.snippet_repo.update_in_project(
                snippet_id,
                project_id,
                name=normalized_name,
                type=snippet_type,
                content=normalized_content,
                file_id=None,
                storage_path=str(stored_file[0]),
                file_name=stored_file[1],
                mime_type=stored_file[2],
                file_size=stored_file[3],
            )
            if updated is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
            await self.db.commit()
            await self.db.refresh(updated)
        except Exception:
            await self.db.rollback()
            stored_file[0].unlink(missing_ok=True)
            raise

        if old_storage_path and old_storage_path != stored_file[0]:
            try:
                old_storage_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Unable to remove replaced snippet asset project_id=%s snippet_id=%s path=%s",
                    project_id,
                    snippet_id,
                    old_storage_path,
                    exc_info=True,
                )
        logger.info(
            "Project media snippet replaced project_id=%s snippet_id=%s actor_id=%s",
            project_id,
            snippet_id,
            actor.id,
        )
        return SnippetOut.model_validate(updated)

    async def delete_snippet(
        self,
        *,
        project_id: UUID,
        snippet_id: UUID,
        actor: User,
    ) -> None:
        await self._ensure_access(project_id, actor)
        self._ensure_can_delete(actor)
        snippet = await self.snippet_repo.get_in_project(snippet_id, project_id)
        if snippet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
        deleted = await self.snippet_repo.delete_in_project(snippet_id, project_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
        if snippet.storage_path:
            Path(snippet.storage_path).unlink(missing_ok=True)
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

    async def snippet_file_bytes(self, snippet: ProjectSnippet) -> bytes | None:
        if not snippet.storage_path:
            return None
        path = Path(snippet.storage_path)
        if not path.is_file():
            raise HTTPException(
                status_code=410,
                detail="Файл заготовки больше недоступен",
            )
        return path.read_bytes()

    async def snippet_preview_path(
        self,
        *,
        project_id: UUID,
        snippet_id: UUID,
        actor: User,
    ) -> tuple[ProjectSnippet, Path]:
        snippet = await self.get_snippet_for_send(
            project_id=project_id,
            snippet_id=snippet_id,
            actor=actor,
        )
        if snippet.type == "text" or not snippet.storage_path:
            raise HTTPException(status_code=404, detail="Предпросмотр файла недоступен")
        path = Path(snippet.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=410, detail="Файл заготовки больше недоступен")
        return snippet, path

    async def _ensure_access(self, project_id: UUID, actor: User) -> None:
        require_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    @staticmethod
    def _ensure_can_create(actor: User) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN, RoleName.MANAGER}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and managers can create project snippets",
            )

    @staticmethod
    def _ensure_can_update(actor: User) -> None:
        ProjectSnippetService._ensure_can_create(actor)

    @staticmethod
    def _ensure_can_delete(actor: User) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can delete project snippets",
            )

    @staticmethod
    def _max_media_size(snippet_type: str) -> int:
        if snippet_type == "photo":
            return settings.CHAT_PHOTO_MAX_MB * 1024 * 1024
        if snippet_type in {"video", "video_note"}:
            return settings.CHAT_VIDEO_MAX_MB * 1024 * 1024
        return settings.CHAT_DOCUMENT_MAX_MB * 1024 * 1024

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(status_code=422, detail="Snippet name cannot be blank")
        if len(normalized_name) > 255:
            raise HTTPException(status_code=422, detail="Snippet name cannot exceed 255 characters")
        return normalized_name

    @staticmethod
    def _normalize_media_content(content: object) -> str | None:
        normalized_content = str(content or "").strip() or None
        if normalized_content and len(normalized_content) > TELEGRAM_CAPTION_LIMIT:
            raise HTTPException(
                status_code=422,
                detail=f"Media caption cannot exceed {TELEGRAM_CAPTION_LIMIT} characters",
            )
        return normalized_content

    async def _store_upload(
        self,
        *,
        project_id: UUID,
        snippet_type: str,
        file: UploadFile,
    ) -> tuple[Path, str, str, int]:
        if snippet_type not in {"photo", "video", "voice", "video_note", "document"}:
            raise HTTPException(status_code=422, detail="Unsupported media snippet type")
        file_name = os.path.basename(file.filename or "attachment")
        if not file_name:
            raise HTTPException(status_code=422, detail="File name is required")
        suffix = Path(file_name).suffix.lower()
        if suffix in {
            ".exe",
            ".bat",
            ".cmd",
            ".com",
            ".scr",
            ".js",
            ".jar",
            ".sh",
            ".php",
            ".py",
        }:
            raise HTTPException(
                status_code=422,
                detail="Этот тип файла нельзя использовать в заготовке.",
            )

        max_size = self._max_media_size(snippet_type)
        storage_dir = Path(settings.CHAT_ATTACHMENT_STORAGE_PATH) / str(project_id) / "snippet_assets"
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{uuid4().hex}{suffix or '.bin'}"
        size = 0
        try:
            with storage_path.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_size:
                        raise HTTPException(status_code=413, detail="Файл слишком большой.")
                    output.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="Uploaded file is empty")
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise
        return storage_path, file_name, file.content_type or "application/octet-stream", size
