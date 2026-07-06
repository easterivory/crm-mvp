from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user
from app.core.constants import RoleName
from app.core.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.tag import TagCreate, TagOut, TagUpdate
from app.services.access_control import require_project_access
from app.services.tag_service import TagService

router = APIRouter(prefix="/tags", tags=["tags"])
project_router = APIRouter(prefix="/projects/{project_id}/tags", tags=["tags"])


@router.get("", response_model=PaginatedResponse[TagOut])
async def list_tags(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TagOut]:
    items, total = await TagService(db).list_tags(
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagOut:
    _ensure_can_create_tag(current_user)
    return await TagService(db).create_tag(project_id, data)


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: UUID,
    data: TagUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagOut:
    _ensure_settings_admin(current_user)
    return await TagService(db).update_tag(tag_id, project_id, data)


@project_router.patch("/{tag_id}", response_model=TagOut)
async def update_project_tag(
    project_id: UUID,
    tag_id: UUID,
    data: TagUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagOut:
    _ensure_project_member(current_user, project_id)
    if data.name is not None:
        _ensure_settings_admin(current_user)
    return await TagService(db).update_tag(tag_id, project_id, data)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_settings_admin(current_user)
    await TagService(db).delete_tag(tag_id, project_id)


@router.post("/leads/{lead_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_tag_to_lead(
    lead_id: UUID,
    tag_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_lead_tag_access(current_user)
    await TagService(db).add_tag_to_lead(
        lead_id=lead_id,
        tag_id=tag_id,
        project_id=project_id,
    )


@router.delete("/leads/{lead_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tag_from_lead(
    lead_id: UUID,
    tag_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_lead_tag_access(current_user)
    await TagService(db).remove_tag_from_lead(
        lead_id=lead_id,
        tag_id=tag_id,
        project_id=project_id,
    )


def _ensure_can_create_tag(current_user) -> None:
    if current_user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN, RoleName.MANAGER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin/admin/manager can create project tags",
        )


def _ensure_settings_admin(current_user) -> None:
    if current_user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin/admin can manage project tags",
        )


def _ensure_project_member(current_user, project_id: UUID) -> None:
    if current_user.role_name not in RoleName.ALL or current_user.role_name == RoleName.BUYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only CRM staff can manage project tags",
        )
    require_project_access(current_user, project_id)


def _ensure_lead_tag_access(current_user) -> None:
    if current_user.role_name == RoleName.BUYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyers have read-only access to leads",
        )
