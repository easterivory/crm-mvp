from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.lander import ProjectDomainCreate, ProjectDomainOut
from app.services.lander_admin_service import LanderAdminService

router = APIRouter(prefix="/projects/{project_id}/domains", tags=["domains"])


@router.get("", response_model=list[ProjectDomainOut])
async def list_project_domains(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectDomainOut]:
    return await LanderAdminService(db).list_domains(
        project_id=project_id,
        actor=current_user,
    )


@router.post("", response_model=ProjectDomainOut, status_code=status.HTTP_201_CREATED)
async def create_project_domain(
    project_id: UUID,
    data: ProjectDomainCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectDomainOut:
    return await LanderAdminService(db).create_domain(
        project_id=project_id,
        data=data,
        actor=current_user,
    )


@router.delete(
    "/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_project_domain(
    project_id: UUID,
    domain_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await LanderAdminService(db).delete_domain(
        project_id=project_id,
        domain_id=domain_id,
        actor=current_user,
    )
