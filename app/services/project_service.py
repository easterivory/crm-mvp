"""
ProjectService - project CRUD and validation.
"""
import re
import unicodedata
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectOut, ProjectStatus, ProjectUpdate


PROJECT_STATUSES: set[str] = {"active", "archived"}


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.project_repo = ProjectRepository(db)

    async def list_projects(
        self,
        limit: int,
        offset: int,
        actor: User,
    ) -> tuple[list[ProjectOut], int]:
        if actor.role_name == RoleName.SUPER_ADMIN:
            projects = await self.project_repo.list(limit=limit, offset=offset)
            total = await self.project_repo.count()
            return [ProjectOut.model_validate(project) for project in projects], total

        if actor.project_id is None:
            return [], 0

        project = await self.project_repo.get_active(actor.project_id)
        projects = [project] if project is not None else []
        total = len(projects)
        return [ProjectOut.model_validate(project) for project in projects], total

    async def create_project(self, data: ProjectCreate, actor: User) -> ProjectOut:
        self._ensure_can_create_project(actor)
        name = self._validate_name(data.name)
        status_value = self._validate_status(data.status)
        sla_threshold_minutes = self._validate_sla(data.sla_threshold_minutes)
        slug = (
            await self._generate_unique_slug(name)
            if data.slug is None
            else await self._validate_explicit_slug(data.slug)
        )

        try:
            project = await self.project_repo.create(
                name=name,
                slug=slug,
                description=data.description,
                status=status_value,
                is_deleted=status_value == "archived",
                sla_threshold_minutes=sla_threshold_minutes,
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project slug already exists",
            ) from exc
        return ProjectOut.model_validate(project)

    async def get_project(self, project_id: UUID, actor: User) -> ProjectOut:
        self._ensure_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return ProjectOut.model_validate(project)

    async def update_project(
        self,
        project_id: UUID,
        data: ProjectUpdate,
        actor: User,
    ) -> ProjectOut:
        self._ensure_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        values = data.model_dump(exclude_unset=True)
        for non_nullable_field in ("name", "slug", "status", "sla_threshold_minutes"):
            if values.get(non_nullable_field) is None:
                values.pop(non_nullable_field, None)

        if "name" in values:
            values["name"] = self._validate_name(values["name"])
        if "slug" in values:
            values["slug"] = await self._validate_explicit_slug(
                values["slug"],
                project_id=project_id,
            )
        if "status" in values:
            values["status"] = self._validate_status(values["status"])
            if values["status"] == "archived":
                values["is_deleted"] = True
        if (
            "sla_threshold_minutes" in values
            and values["sla_threshold_minutes"] is not None
        ):
            values["sla_threshold_minutes"] = self._validate_sla(
                values["sla_threshold_minutes"]
            )

        if not values:
            return ProjectOut.model_validate(project)

        project = await self.project_repo.update_active(project_id, **values)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return ProjectOut.model_validate(project)

    async def archive_project(self, project_id: UUID, actor: User) -> None:
        if actor.role_name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can archive projects",
            )
        archived = await self.project_repo.archive(project_id)
        if not archived:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

    async def _generate_unique_slug(self, name: str) -> str:
        base_slug = self._slugify(name)
        slug = base_slug
        suffix = 2
        while await self.project_repo.slug_exists(slug):
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        return slug

    async def _validate_explicit_slug(
        self,
        slug: str,
        project_id: UUID | None = None,
    ) -> str:
        normalized = self._normalize_slug(slug)
        if await self.project_repo.slug_exists(normalized, exclude_id=project_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project slug already exists",
            )
        return normalized

    @staticmethod
    def _ensure_can_create_project(actor: User) -> None:
        if actor.role_name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can create projects",
            )

    @staticmethod
    def _ensure_project_access(actor: User, project_id: UUID) -> None:
        if actor.role_name == RoleName.SUPER_ADMIN:
            return
        if actor.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project is not accessible for current user",
            )

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project name must not be empty",
            )
        return normalized

    @staticmethod
    def _validate_status(project_status: ProjectStatus) -> str:
        if project_status not in PROJECT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project status must be active or archived",
            )
        return project_status

    @staticmethod
    def _validate_sla(sla_threshold_minutes: int) -> int:
        if sla_threshold_minutes < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="SLA threshold must be greater than zero",
            )
        return sla_threshold_minutes

    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        normalized = cls._slugify(value)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project slug must not be empty",
            )
        return normalized

    @staticmethod
    def _slugify(value: str) -> str:
        ascii_value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
        return slug or "project"
