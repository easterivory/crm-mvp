from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.services.lander_service import LanderNotFoundError, LanderService

router = APIRouter(tags=["public-landers"])

SYSTEM_ROOT_PATHS = frozenset(
    {
        "api",
        "docs",
        "redoc",
        "openapi.json",
        "health",
        "static",
        "favicon.ico",
    }
)


@router.get("/l/{slug}/{asset_path:path}", response_class=FileResponse, include_in_schema=False)
async def render_prefixed_lander_asset(
    slug: str,
    asset_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    host = request.headers.get("host", "")
    try:
        file_path, media_type = await LanderService(db).resolve_custom_asset(
            host=host,
            slug=slug,
            asset_path=asset_path,
        )
    except LanderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lander asset not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return FileResponse(file_path, media_type=media_type)


@router.get("/l/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def render_prefixed_lander(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    return await _render_lander(slug=slug, request=request, db=db)


@router.get("/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def render_short_lander(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if slug.lower() in SYSTEM_ROOT_PATHS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return await _render_lander(slug=slug, request=request, db=db)


async def _render_lander(
    *,
    slug: str,
    request: Request,
    db: AsyncSession,
) -> HTMLResponse:
    host = request.headers.get("host", "")
    try:
        html_content = await LanderService(db).render_lander_html(
            host=host,
            slug=slug,
            query_params=request.query_params,
        )
    except LanderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lander not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return HTMLResponse(content=html_content)
