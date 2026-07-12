from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.services.lander_service import LanderNotFoundError, LanderService

router = APIRouter(tags=["public-landers"])

SYSTEM_ROOT_PATHS = frozenset(
    {
        "api",
        "analytics",
        "bots",
        "broadcasts",
        "buyers",
        "chats",
        "dashboard",
        "docs",
        "favicon.ico",
        "funnels",
        "google-sheets",
        "health",
        "landers",
        "leads",
        "login",
        "openapi.json",
        "partners",
        "profile",
        "projects",
        "redoc",
        "settings",
        "static",
        "team",
        "tracking",
        "users",
    }
)
LANDER_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@router.get("/l/{slug}/{asset_path:path}", response_class=FileResponse, include_in_schema=False)
async def render_prefixed_lander_asset(
    slug: str,
    asset_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    host = _request_host(request)
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


@router.post("/l/{slug}/bridge/{start_key}", include_in_schema=False)
async def update_lander_bridge(
    slug: str,
    start_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        content_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        content_length = 4097
    if content_length > 4096:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload is too large",
        )
    host = _request_host(request)
    try:
        lander = await LanderService(db).resolve_lander_request(host=host, slug=slug)
    except (LanderNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lander not found",
        ) from exc

    bridge = await LanderService(db).utm_bridge.load_lander_start(start_key)
    if bridge is None or lander.tracking_link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bridge not found")
    ref_code, _ = bridge
    expected_code = (lander.tracking_link.code or lander.tracking_link.ref_code or "").strip()
    if ref_code != expected_code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bridge not found")

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    context = _browser_context_from_request(request)
    context.pop("event_source_url", None)
    context["fbp"] = payload.get("_fbp") or payload.get("fbp")
    context["fbc"] = payload.get("_fbc") or payload.get("fbc")
    context["event_source_url"] = payload.get("event_source_url")
    updated = await LanderService(db).utm_bridge.update_lander_start_context(
        start_key,
        browser_context=context,
    )
    return {"updated": updated}


@router.get("/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def render_short_lander(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if slug.lower() in SYSTEM_ROOT_PATHS or not LANDER_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return await _render_lander(slug=slug, request=request, db=db)


async def _render_lander(
    *,
    slug: str,
    request: Request,
    db: AsyncSession,
) -> HTMLResponse:
    host = _request_host(request)
    try:
        html_content = await LanderService(db).render_lander_html(
            host=host,
            slug=slug,
            query_params=request.query_params,
            browser_context=_browser_context_from_request(request),
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

    return HTMLResponse(
        content=html_content,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "CDN-Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Surrogate-Control": "no-store",
            "Vary": "Host, X-Forwarded-Host, Cookie, User-Agent",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


def _browser_context_from_request(request: Request) -> dict[str, str]:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", maxsplit=1)[0].strip()
    if not client_ip and request.client is not None:
        client_ip = request.client.host

    context: dict[str, str] = {}
    fbp = request.cookies.get("_fbp")
    if fbp:
        context["fbp"] = fbp
    fbc = request.cookies.get("_fbc")
    if fbc:
        context["fbc"] = fbc
    user_agent = request.headers.get("user-agent")
    if user_agent:
        context["client_user_agent"] = user_agent
    if client_ip:
        context["client_ip_address"] = client_ip
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", maxsplit=1)[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = _request_host(request)
    path_and_query = request.url.path
    if request.url.query:
        path_and_query = f"{path_and_query}?{request.url.query}"
    context["event_source_url"] = f"{scheme}://{host}{path_and_query}"
    return context


def _request_host(request: Request) -> str:
    forwarded_host = request.headers.get("x-forwarded-host", "")
    if forwarded_host:
        return forwarded_host.split(",", maxsplit=1)[0].strip()
    return request.headers.get("host", "")
