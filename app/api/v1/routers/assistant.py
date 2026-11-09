"""Distinct trust boundaries: cloud tools cannot call human approval endpoints."""
import json
import asyncio
import logging
import time
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.api.v1.dependencies import get_current_user
from app.core.assistant import SCOPES, assistant_db, enabled, fail, heavy_lease, issuer_url, limit, now, project_policy, resource_url, user_policy
from app.core.config import settings
from app.core.assistant import assistant_base_url
from app.models import Project
from app.models.assistant import AssistantConnection, AssistantProposal
from app.schemas.assistant import ApprovalIn, AuthorizeIn, SecureInputIn
from app.services.assistant_changes import AssistantChanges, put_input, cipher
from app.services.assistant_oauth import authenticate, authorization_parameters, authorize, exchange
from app.services.assistant_tools import AssistantTools, TOOLS, safe_text

router = APIRouter(prefix="/api/v1/assistant", tags=["cloud-assistant"])
oauth_router = APIRouter(tags=["assistant-oauth"])
logger = logging.getLogger(__name__)


async def json_body(request, model=None):
    raw = await small_body(request)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError()
        pending = [(data, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 16: raise ValueError()
            if isinstance(value, dict): pending.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list): pending.extend((v, depth + 1) for v in value)
        return model.model_validate(data) if model else data
    except (ValueError, RecursionError, ValidationError): fail("invalid_arguments", 422)


async def small_body(request, size=32768):
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > size: fail("request_too_large", 413)
    return bytes(body)


def ui_origin(request):
    p = urlsplit(assistant_base_url())
    if request.headers.get("origin") != f"{p.scheme}://{p.netloc}": fail("interactive_approval_required")


async def cloud_context(request, db):
    await limit("auth", 30, 1)
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "): fail("unauthenticated", 401)
    return await authenticate(db, header[7:])


@router.get("/status")
async def module_status(actor=Depends(get_current_user)):
    if actor.role_name != "super_admin": fail("forbidden")
    allowed = settings.ASSISTANT_ENABLED and str(actor.id) in {s.strip() for s in settings.ASSISTANT_ALLOWED_USER_IDS.split(",")}
    return {"enabled": settings.ASSISTANT_ENABLED, "allowed": allowed,
        "mcp_enabled": settings.ASSISTANT_MCP_ENABLED if allowed else False,
        "changes_enabled": settings.ASSISTANT_CHANGES_ENABLED if allowed else False,
        "resource_url": settings.ASSISTANT_MCP_RESOURCE_URL if allowed else None,
        "scopes": sorted(SCOPES) if allowed else []}


@router.get("/projects")
async def allowed_projects(actor=Depends(get_current_user), db=Depends(assistant_db)):
    user_policy(actor)
    rows = (await db.scalars(select(Project).where(Project.is_deleted.is_(False), Project.status == "active"))).all()
    result = []
    for row in rows:
        try: project_policy(actor, row.id)
        except HTTPException: continue
        result.append({"id": str(row.id), "name": safe_text(row.name)})
    return result


@router.get("/authorization")
async def authorization_details(query: str, actor=Depends(get_current_user)):
    user_policy(actor)
    p, _, scopes, _ = authorization_parameters(query)
    return {"client_id": p["client_id"], "scopes": scopes, "resource": resource_url()}


@router.post("/authorize")
async def consent(request: Request, actor=Depends(get_current_user), db=Depends(assistant_db)):
    ui_origin(request)
    data = await json_body(request, AuthorizeIn)
    await limit(f"consent:{actor.id}", 10, 60)
    return await authorize(db, actor, data)


@router.get("/connections")
async def connections(actor=Depends(get_current_user), db=Depends(assistant_db)):
    user_policy(actor)
    rows = (await db.scalars(select(AssistantConnection).where(AssistantConnection.user_id == actor.id)
        .order_by(AssistantConnection.created_at.desc()).limit(50))).all()
    return [{"id": str(r.id), "client_id": r.client_id, "project_ids": r.project_ids, "scopes": r.scopes,
        "created_at": r.created_at, "revoked_at": r.revoked_at, "last_used_at": r.last_used_at} for r in rows]


@router.post("/connections/{connection_id}/revoke")
async def revoke(connection_id: UUID, request: Request, actor=Depends(get_current_user), db=Depends(assistant_db)):
    user_policy(actor); ui_origin(request)
    row = await db.scalar(select(AssistantConnection).where(AssistantConnection.id == connection_id,
        AssistantConnection.user_id == actor.id).with_for_update())
    if not row: fail("not_found", 404)
    row.revoked_at = now()
    from app.services.audit_service import AuditService
    for project_id in row.project_ids:
        await AuditService(db).log(project_id=UUID(project_id), actor_id=actor.id, action="assistant.revoke",
            entity_type="assistant_connection", entity_id=row.id, meta={"source": "cloud_assistant"})
    return {"revoked": True}


@router.post("/secure-inputs")
async def secure_input(request: Request, actor=Depends(get_current_user), db=Depends(assistant_db)):
    ui_origin(request)
    data = await json_body(request, SecureInputIn)
    try: return await put_input(db, actor, data)
    except ValidationError: fail("invalid_source_url", 422)


@router.get("/proposals")
async def proposals(project_id: UUID, actor=Depends(get_current_user), db=Depends(assistant_db)):
    project_policy(actor, project_id)
    rows = (await db.scalars(select(AssistantProposal).where(AssistantProposal.project_id == project_id,
        AssistantProposal.user_id == actor.id).order_by(AssistantProposal.created_at.desc()).limit(50))).all()
    return [AssistantChanges.public(row) for row in rows]


@router.post("/secure-inputs/{input_id}/reveal")
async def reveal_input(input_id: UUID, request: Request, actor=Depends(get_current_user), db=Depends(assistant_db)):
    from app.models.assistant import AssistantSecureInput
    ui_origin(request)
    row = await db.get(AssistantSecureInput, input_id)
    if row is None or row.user_id != actor.id or row.expires_at <= now(): fail("not_found", 404)
    project_policy(actor, row.project_id)
    return JSONResponse({"value": cipher().decrypt(row.encrypted_value).decode()}, headers={"Cache-Control": "no-store"})


@router.get("/proposals/{proposal_id}")
async def proposal(proposal_id: UUID, actor=Depends(get_current_user), db=Depends(assistant_db)):
    user_policy(actor)
    row = await db.scalar(select(AssistantProposal).where(AssistantProposal.id == proposal_id, AssistantProposal.user_id == actor.id))
    if not row: fail("not_found", 404)
    project_policy(actor, row.project_id)
    return AssistantChanges.public(row)


@router.post("/proposals/{proposal_id}/approve-and-apply")
async def approve(proposal_id: UUID, request: Request, actor=Depends(get_current_user), db=Depends(assistant_db)):
    ui_origin(request)
    data = await json_body(request, ApprovalIn)
    await limit(f"apply:{actor.id}", 10, 60)
    return await AssistantChanges(db).apply(actor, proposal_id, data.expected_plan_hash)


@router.post("/proposals/{proposal_id}/{action}")
async def decline(proposal_id: UUID, action: str, request: Request, actor=Depends(get_current_user), db=Depends(assistant_db)):
    ui_origin(request)
    if action not in {"reject", "cancel"}: fail("not_found", 404)
    service = AssistantChanges(db)
    row = await service.owned(actor, proposal_id, lock=True)
    if row.status not in {"draft", "pending_approval"}: fail("proposal_not_pending", 409)
    row.status = "rejected" if action == "reject" else "cancelled"
    await service.audit(row, actor, "assistant." + action)
    return service.public(row)


@router.get("/session")
async def session(request: Request, db=Depends(assistant_db)):
    actor, conn, scopes = await cloud_context(request, db)
    return {"user_id": str(actor.id), "client_id": conn.client_id, "scopes": sorted(scopes)}


@router.get("/tool-schemas")
async def tool_schemas(request: Request, db=Depends(assistant_db)):
    _, _, scopes = await cloud_context(request, db)
    return [{"name": name, "inputSchema": model.model_json_schema(), "readOnlyHint": name != "crm_prepare_change"}
        for name, (scope, model) in TOOLS.items() if scope in scopes]


@router.post("/tools/{name}")
async def tool(name: str, request: Request, db=Depends(assistant_db)):
    actor, conn, scopes = await cloud_context(request, db)
    await limit("global", 5, 1)
    await limit(f"read:{conn.id}", 30, 60)
    if name == "crm_prepare_change": await limit(f"prepare:{conn.id}", 5, 60)
    arguments = await json_body(request)
    started = time.monotonic()
    try:
        async with heavy_lease():
            result = await asyncio.wait_for(AssistantTools(db, actor, conn, scopes).call(name, arguments), timeout=8)
            logger.info("Assistant tool request_id=%s tool=%s user_id=%s connection_id=%s elapsed_ms=%s",
                result["request_id"], name if name in TOOLS else "unknown", actor.id, conn.id, int((time.monotonic() - started) * 1000))
            return result
    except ValidationError: fail("invalid_arguments", 422)
    except asyncio.TimeoutError: fail("temporarily_unavailable", 503)


@oauth_router.get("/assistant-oauth/.well-known/oauth-authorization-server")
async def metadata():
    enabled(mcp=True)
    return {"issuer": issuer_url(), "authorization_endpoint": issuer_url() + "/authorize", "token_endpoint": issuer_url() + "/token",
        "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        "authorization_response_iss_parameter_supported": True, "scopes_supported": sorted(SCOPES)}


@oauth_router.get("/.well-known/oauth-authorization-server/assistant-oauth", include_in_schema=False)
async def metadata_standard(): return await metadata()


@oauth_router.get("/assistant-oauth/authorize")
async def authorize_redirect(request: Request):
    query = request.url.query
    if len(query) > 8192: fail("invalid_arguments", 422)
    authorization_parameters(query)
    return RedirectResponse(assistant_base_url() + "/settings?" + urlencode({"assistant_authorize": query}), status_code=303)


@oauth_router.post("/assistant-oauth/token")
async def token_exchange(request: Request, db=Depends(assistant_db)):
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded": fail("invalid_request", 400)
    await limit("oauth-exchange", 30, 60)
    try: body = (await small_body(request, 8192)).decode()
    except UnicodeError: fail("invalid_request", 400)
    response, status = await exchange(db, body, dict(request.headers.items()) | {"Authorization": request.headers.get("authorization", "")})
    return JSONResponse(jsonable_encoder(response), status_code=status, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
