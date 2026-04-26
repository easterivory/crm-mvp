from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id
from app.core.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.tag import TagCreate, TagOut

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=PaginatedResponse[TagOut])
async def list_tags(
    limit: int = 50,
    offset: int = 0,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TagOut]:
    raise NotImplementedError


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> TagOut:
    raise NotImplementedError


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    raise NotImplementedError


@router.post("/leads/{lead_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_tag_to_lead(
    lead_id: UUID,
    tag_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    raise NotImplementedError


@router.delete("/leads/{lead_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tag_from_lead(
    lead_id: UUID,
    tag_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    raise NotImplementedError
