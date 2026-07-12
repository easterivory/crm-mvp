from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse

from app.core.config import settings
from app.services.lander_service import LanderService


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


def _is_technical_domain(request: Request) -> bool:
    host = LanderService.normalize_host(request.headers.get("host", ""))
    technical_domain = LanderService.normalize_host(settings.LANDER_TECH_DOMAIN)
    return bool(technical_domain and host == technical_domain)


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
async def render_frontend(request: Request) -> Response:
    if _is_technical_domain(request):
        if request.url.path != "/":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return HTMLResponse(
            "<!doctype html><html><head><meta charset='utf-8'><meta name='robots' "
            "content='noindex,nofollow'><title>Landing gateway</title></head>"
            "<body>Landing gateway is ready.</body></html>",
            headers={
                "Cache-Control": "no-store",
                "CDN-Cache-Control": "no-store",
                "Surrogate-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )
    return _frontend_index_response()


@router.get("/funnels/{funnel_id}/builder")
async def render_funnel_builder(funnel_id: str, request: Request) -> FileResponse:
    del funnel_id
    if _is_technical_domain(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _frontend_index_response()
