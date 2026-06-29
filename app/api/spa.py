from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse


router = APIRouter(include_in_schema=False)

FRONTEND_INDEX_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
)


def _frontend_index_response() -> FileResponse:
    if not FRONTEND_INDEX_PATH.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Frontend build is unavailable",
        )

    return FileResponse(
        FRONTEND_INDEX_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/")
@router.get("/login")
@router.get("/dashboard")
@router.get("/analytics")
@router.get("/chats")
@router.get("/funnels")
@router.get("/broadcasts")
@router.get("/bots")
@router.get("/leads")
@router.get("/tracking")
@router.get("/docs")
@router.get("/settings")
async def render_frontend() -> FileResponse:
    return _frontend_index_response()


@router.get("/funnels/{funnel_id}/builder")
async def render_funnel_builder(funnel_id: str) -> FileResponse:
    del funnel_id
    return _frontend_index_response()
