from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.schemas.snippet import SnippetCreate, SnippetOut, SnippetUpdate
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


@router.post("/media", response_model=SnippetOut, status_code=status.HTTP_201_CREATED)
async def create_project_media_snippet(
    project_id: UUID,
    name: str = Form(...),
    type: str = Form(...),
    content: str | None = Form(default=None),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SnippetOut:
    return await ProjectSnippetService(db).create_uploaded_snippet(
        project_id=project_id,
        actor=current_user,
        name=name,
        snippet_type=type,
        content=content,
        file=file,
    )


@router.patch("/{snippet_id}", response_model=SnippetOut)
async def update_project_snippet(
    project_id: UUID,
    snippet_id: UUID,
    data: SnippetUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SnippetOut:
    return await ProjectSnippetService(db).update_snippet(
        project_id=project_id,
        snippet_id=snippet_id,
        actor=current_user,
        data=data,
    )


@router.put("/{snippet_id}/media", response_model=SnippetOut)
async def replace_project_media_snippet(
    project_id: UUID,
    snippet_id: UUID,
    name: str = Form(...),
    type: str = Form(...),
    content: str | None = Form(default=None),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SnippetOut:
    return await ProjectSnippetService(db).replace_uploaded_snippet(
        project_id=project_id,
        snippet_id=snippet_id,
        actor=current_user,
        name=name,
        snippet_type=type,
        content=content,
        file=file,
    )


@router.get("/{snippet_id}/media", response_class=FileResponse)
async def preview_project_media_snippet(
    project_id: UUID,
    snippet_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    snippet, path = await ProjectSnippetService(db).snippet_preview_path(
        project_id=project_id,
        snippet_id=snippet_id,
        actor=current_user,
    )
    return FileResponse(
        path,
        media_type=snippet.mime_type or "application/octet-stream",
        filename=snippet.file_name or path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=60"},
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
