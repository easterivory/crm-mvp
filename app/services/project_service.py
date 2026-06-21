"""
ProjectService - project CRUD and validation.
"""
import re
import unicodedata
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType, RoleName
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_metrics_repository import ProjectMetricsRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectDashboardHeaderOut,
    ProjectOut,
    ProjectStatus,
    ProjectTranslationUpdate,
    ProjectUpdate,
)
from app.services.audit_service import AuditService
from app.services.access_control import accessible_project_ids, require_project_access


PROJECT_STATUSES: set[str] = {"active", "archived"}


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.project_repo = ProjectRepository(db)
        self.metrics_repo = ProjectMetricsRepository(db)
        self.audit = AuditService(db)

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

        project_ids = accessible_project_ids(actor)
        if not project_ids:
            return [], 0

        projects = await self.project_repo.list_by_ids(project_ids)
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

    async def update_translation_settings(
        self,
        project_id: UUID,
        data: ProjectTranslationUpdate,
        actor: User,
    ) -> ProjectOut:
        self._ensure_translation_settings_admin(actor)
        self._ensure_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        values = data.model_dump(exclude_unset=True)
        for field_name in ("operator_lang", "default_client_lang"):
            if field_name not in values:
                continue
            if values[field_name] is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field_name} must not be null",
                )
            values[field_name] = self._validate_language_code(
                values[field_name],
                field_name=field_name,
            )

        if (
            values.get("is_translation_enabled") is None
            and "is_translation_enabled" in values
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="is_translation_enabled must not be null",
            )

        if not values:
            return ProjectOut.model_validate(project)

        updated = await self.project_repo.update_active(project_id, **values)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return ProjectOut.model_validate(updated)

    async def archive_project(self, project_id: UUID, actor: User) -> None:
        if actor.role_name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can archive projects",
            )
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        if await self.project_repo.count() <= 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot archive the last active project",
            )
        archived = await self.project_repo.archive(project_id)
        if not archived:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.PROJECT_ARCHIVED,
            entity_type=EntityType.PROJECT,
            entity_id=project_id,
            actor_id=actor.id,
            meta={"name": project.name, "slug": project.slug},
        )

    async def restore_project(self, project_id: UUID, actor: User) -> ProjectOut:
        if actor.role_name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can restore projects",
            )
        project = await self.project_repo.restore(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.PROJECT_RESTORED,
            entity_type=EntityType.PROJECT,
            entity_id=project_id,
            actor_id=actor.id,
            meta={"name": project.name, "slug": project.slug},
        )
        return ProjectOut.model_validate(project)

    async def dashboard_header(
        self,
        project_id: UUID,
        actor: User,
    ) -> ProjectDashboardHeaderOut:
        self._ensure_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        metrics = await self.metrics_repo.header_metrics(project_id, date.today())
        return ProjectDashboardHeaderOut(**metrics)

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
    def _ensure_translation_settings_admin(actor: User) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin/super_admin can manage translation settings",
            )

    @staticmethod
    def _ensure_project_access(actor: User, project_id: UUID) -> None:
        require_project_access(actor, project_id)

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

    @staticmethod
    def _validate_language_code(value: str, *, field_name: str) -> str:
        normalized = value.strip().replace("_", "-").lower()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must not be empty",
            )
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must be a valid language code",
            )
        return normalized

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
