from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.core.config import settings
from app.services.lander_service import LanderService


router = APIRouter(include_in_schema=False)

FRONTEND_INDEX_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
)
LOCAL_CRM_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
PUBLIC_NOT_FOUND_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta name="theme-color" content="#090b11">
  <title>Page unavailable</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; min-height: 100svh; display: grid; place-items: center; background: #090b11; color: #f4f4f5; }
    main { width: min(100% - 40px, 460px); text-align: center; }
    .status { display: grid; width: 58px; height: 58px; margin: 0 auto 24px; place-items: center; border: 1px solid #303541; border-radius: 8px; background: #11141c; color: #a1a1aa; font-size: 14px; font-weight: 700; letter-spacing: 0; }
    h1 { margin: 0; font-size: clamp(26px, 6vw, 34px); line-height: 1.15; letter-spacing: 0; }
    p { margin: 14px auto 0; max-width: 390px; color: #8b909c; font-size: 15px; line-height: 1.6; letter-spacing: 0; }
  </style>
</head>
<body>
  <main>
    <div class="status" aria-hidden="true">404</div>
    <h1>Page unavailable</h1>
    <p>This address is unavailable. Check the link and try again.</p>
  </main>
</body>
</html>"""


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


def _public_not_found_response() -> HTMLResponse:
    return HTMLResponse(
        PUBLIC_NOT_FOUND_HTML,
        status_code=status.HTTP_404_NOT_FOUND,
        headers={
            "Cache-Control": "no-store",
            "CDN-Cache-Control": "no-store",
            "Surrogate-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
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
@router.get("/calculator")
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
        return _public_not_found_response()
    return _frontend_index_response()


@router.get("/funnels/{funnel_id}/builder")
async def render_funnel_builder(funnel_id: str, request: Request) -> Response:
    del funnel_id
    if not _is_crm_application_domain(request):
        return _public_not_found_response()
    return _frontend_index_response()
