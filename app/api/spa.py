from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.services.lander_service import LanderService


router = APIRouter(include_in_schema=False)

FRONTEND_INDEX_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
)
LOCAL_CRM_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


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


def _configured_crm_hosts() -> frozenset[str]:
    raw_values = [settings.BASE_URL, *settings.CRM_PUBLIC_HOSTS.split(",")]
    hosts: set[str] = set()
    for raw_value in raw_values:
        value = raw_value.strip()
        if not value:
            continue
        try:
            parsed = urlsplit(value if "://" in value else f"//{value}")
            host = LanderService.normalize_host(parsed.hostname or "")
        except ValueError:
            continue
        if host:
            hosts.add(host)

    if not hosts.difference(LOCAL_CRM_HOSTS):
        technical_host = LanderService.normalize_host(settings.LANDER_TECH_DOMAIN)
        technical_labels = technical_host.split(".")
        if len(technical_labels) >= 3:
            hosts.add(".".join(technical_labels[1:]))

    if hosts.intersection(LOCAL_CRM_HOSTS):
        hosts.update(LOCAL_CRM_HOSTS)
    return frozenset(hosts)


def _is_crm_application_domain(request: Request) -> bool:
    host = LanderService.normalize_host(request.headers.get("host", ""))
    return bool(host and host in _configured_crm_hosts())


@router.get("/api/ui-host-context")
async def get_ui_host_context(request: Request) -> JSONResponse:
    return JSONResponse(
        {"crm_ui_allowed": _is_crm_application_domain(request)},
        headers={
            "Cache-Control": "no-store",
            "CDN-Cache-Control": "no-store",
            "Surrogate-Control": "no-store",
            "Vary": "Host, X-Forwarded-Host",
        },
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
async def render_frontend(request: Request) -> Response:
    if not _is_crm_application_domain(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _frontend_index_response()


@router.get("/funnels/{funnel_id}/builder")
async def render_funnel_builder(funnel_id: str, request: Request) -> FileResponse:
    del funnel_id
    if not _is_crm_application_domain(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _frontend_index_response()
