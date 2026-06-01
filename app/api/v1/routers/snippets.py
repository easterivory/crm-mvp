from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.schemas.snippet import SnippetCreate, SnippetOut
from app.services.project_snippet_service import ProjectSnippetService

router = APIRouter(prefix="/projects/{project_id}/snippets", tags=["snippets"])


@router.get("", response_model=list[SnippetOut])
async def list_project_snippets(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SnippetOut]:
    return await ProjectSnippetService(db).list_snippets(
        project_id=project_id,
        actor=current_user,
    )


@router.post("", response_model=SnippetOut, status_code=status.HTTP_201_CREATED)
async def create_project_snippet(
    project_id: UUID,
    data: SnippetCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SnippetOut:
    return await ProjectSnippetService(db).create_snippet(
        project_id=project_id,
        actor=current_user,
        data=data,
    )


@router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_snippet(
    project_id: UUID,
    snippet_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ProjectSnippetService(db).delete_snippet(
        project_id=project_id,
        snippet_id=snippet_id,
        actor=current_user,
    )
