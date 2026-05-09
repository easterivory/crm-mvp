"""
ProjectService - project CRUD and validation.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.project_repo = ProjectRepository(db)

    async def list_projects(
        self,
        limit: int,
        offset: int,
    ) -> tuple[list[ProjectOut], int]:
        projects = await self.project_repo.list(limit=limit, offset=offset)
        total = await self.project_repo.count()
        return [ProjectOut.model_validate(project) for project in projects], total

    async def create_project(self, data: ProjectCreate) -> ProjectOut:
        name = self._validate_name(data.name)
        sla_threshold_minutes = self._validate_sla(data.sla_threshold_minutes)

        project = await self.project_repo.create(
            name=name,
            sla_threshold_minutes=sla_threshold_minutes,
        )
        return ProjectOut.model_validate(project)

    async def get_project(self, project_id: UUID) -> ProjectOut:
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
    ) -> ProjectOut:
        values = data.model_dump(exclude_unset=True)

        if "name" in values and values["name"] is not None:
            values["name"] = self._validate_name(values["name"])
        if (
            "sla_threshold_minutes" in values
            and values["sla_threshold_minutes"] is not None
        ):
            values["sla_threshold_minutes"] = self._validate_sla(
                values["sla_threshold_minutes"]
            )

        if not values:
            return await self.get_project(project_id)

        project = await self.project_repo.update_active(project_id, **values)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return ProjectOut.model_validate(project)

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
    def _validate_sla(sla_threshold_minutes: int) -> int:
        if sla_threshold_minutes < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="SLA threshold must be greater than zero",
            )
        return sla_threshold_minutes
