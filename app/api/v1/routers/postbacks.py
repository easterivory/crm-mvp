from __future__ import annotations

from typing import Any
from uuid import UUID
import asyncio
import json
import logging
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.postback import (
    LeadEventCreate,
    LeadEventOut,
    PostbackDryRun,
    PostbackBindingCreate,
    PostbackEndpointCreate,
    PostbackEndpointOut,
    PostbackEndpointUpdate,
    PostbackReceiptOut,
    PublicPostbackResult,
)
from app.services.lead_event_service import LeadEventService
from app.services.postback_endpoint_service import PostbackEndpointService


router = APIRouter(prefix="/postback-endpoints", tags=["postback-endpoints"])
public_router = APIRouter(prefix="/pb", tags=["public-postbacks"])
lead_event_router = APIRouter(prefix="/leads", tags=["lead-events"])
logger = logging.getLogger(__name__)


@router.get("/transport")
async def transport_info(project_id: UUID = Depends(get_current_project_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.core.config import settings
    from app.core.constants import RoleName
    from app.models.postback import PostbackRelayHealth
    from app.services.postback_relay_service import public_base_url, project_scope
    PostbackEndpointService._ensure_manage_access(current_user, project_id)
    scope = project_scope() if settings.POSTBACK_RELAY_ENABLED else set()
    relay = settings.POSTBACK_RELAY_ENABLED and (scope is None or project_id in scope)
    configured = relay and bool(settings.POSTBACK_PUBLIC_BASE_URL.strip())
    origin = public_base_url() if configured else settings.BASE_URL.rstrip("/")
    health = await db.scalar(select(PostbackRelayHealth).order_by(PostbackRelayHealth.seen_at.desc()).limit(1)) if relay else None
    age = None
    if health:
        from app.services.postback_contract_service import aware
        age = max(0, (datetime.now(timezone.utc) - aware(health.seen_at)).total_seconds())
    return {"origin": origin, "relay_origin": settings.POSTBACK_PUBLIC_BASE_URL.strip() or None,
        "mode": "relay" if configured else "direct", "relay_enabled_for_project": relay,
        "configuration_status": "relay_configured" if configured else "relay_waiting_for_domain" if relay else "direct",
        "last_heartbeat_age_seconds": age, "gateway_reachable": age is not None and age < 90,
        "queue": health.stats_json if health and current_user.role_name == RoleName.SUPER_ADMIN else None,
        "legacy_status_route_enabled": settings.LEGACY_PARTNER_POSTBACKS_ENABLED}


async def managed_endpoint(db, endpoint_id, project_id, actor):
    from sqlalchemy import select
    from app.models.postback import PostbackEndpoint
    from fastapi import HTTPException
    PostbackEndpointService._ensure_manage_access(actor, project_id)
    endpoint = await db.scalar(select(PostbackEndpoint).where(PostbackEndpoint.id == endpoint_id,
        PostbackEndpoint.project_id == project_id, PostbackEndpoint.is_archived.is_(False)))
    if endpoint is None:
        raise HTTPException(404)
    return endpoint


@router.post("/{endpoint_id}/restore")
async def restore_endpoint(endpoint_id: UUID, project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models.postback import PostbackEndpoint
    from fastapi import HTTPException
    PostbackEndpointService._ensure_manage_access(current_user, project_id)
    row = await db.scalar(select(PostbackEndpoint).where(PostbackEndpoint.id == endpoint_id,
        PostbackEndpoint.project_id == project_id).with_for_update())
    if row is None:
        raise HTTPException(404)
    row.is_archived = False; row.is_active = False
    await db.flush()
    return {"is_archived": False, "is_active": False}


@router.get("/followups")
async def followups(project_id: UUID = Depends(get_current_project_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models.postback import PostbackFollowup
    PostbackEndpointService._ensure_manage_access(current_user, project_id)
    jobs = (await db.scalars(select(PostbackFollowup).where(PostbackFollowup.project_id == project_id,
        PostbackFollowup.status == "review").order_by(PostbackFollowup.created_at.desc()).limit(50))).all()
    return [{"id": str(j.id), "kind": j.kind, "error": j.error, "receipt_id": str(j.receipt_id)} for j in jobs]


@router.post("/followups/{job_id}/resolve")
async def resolve_followup(job_id: UUID, retry: bool = Query(False), project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models.postback import PostbackFollowup
    from fastapi import HTTPException
    PostbackEndpointService._ensure_manage_access(current_user, project_id)
    job = await db.scalar(select(PostbackFollowup).where(PostbackFollowup.id == job_id,
        PostbackFollowup.project_id == project_id).with_for_update())
    if not job or job.status != "review":
        raise HTTPException(409)
    job.status = "pending" if retry else "done"
    job.error = f"Resolved by {current_user.id}; retry={retry}"
    await db.flush()
    return {"status": job.status}


@router.post("/{endpoint_id}/dry-run")
async def dry_run(endpoint_id: UUID, data: PostbackDryRun,
    project_id: UUID = Depends(get_current_project_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.postback_contract_service import PostbackContractService
    endpoint = await managed_endpoint(db, endpoint_id, project_id, current_user)
    return await PostbackContractService(db).receive(token=endpoint.secret_token, method="POST",
        query=data.query_payload, body=data.body_payload, dry_run=True)


@router.post("/{endpoint_id}/bindings")
async def create_binding(endpoint_id: UUID, data: PostbackBindingCreate,
    project_id: UUID = Depends(get_current_project_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.postback_contract_service import PostbackContractService
    endpoint = await managed_endpoint(db, endpoint_id, project_id, current_user)
    row = await PostbackContractService(db).bind(endpoint, data)
    return {"id": str(row.id), "lead_id": str(row.lead_id), "external_id": row.external_id}


@router.post("/{endpoint_id}/close-legacy-status-route")
async def close_legacy_status_route(endpoint_id: UUID, project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.models.partner import PartnerIntegration
    from fastapi import HTTPException
    endpoint = await managed_endpoint(db, endpoint_id, project_id, current_user)
    if endpoint.processing_kind != "submission_status" or not endpoint.partner_integration_id:
        raise HTTPException(422, "Select a submission-status endpoint")
    integration = await db.get(PartnerIntegration, endpoint.partner_integration_id)
    integration.legacy_callback_disabled = True
    await db.flush()
    return {"legacy_callback_disabled": True}


@router.post("/{endpoint_id}/receipts/{receipt_id}/reprocess", response_model=PublicPostbackResult)
async def reprocess(endpoint_id: UUID, receipt_id: UUID, use_current_contract: bool = Query(False),
    project_id: UUID = Depends(get_current_project_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, update
    from app.models.postback import PostbackReceipt, PostbackRelayDelivery, PostbackEndpointRevision
    from app.services.postback_contract_service import PostbackContractService, now
    from fastapi import HTTPException
    endpoint = await managed_endpoint(db, endpoint_id, project_id, current_user)
    receipt = await db.scalar(select(PostbackReceipt).where(PostbackReceipt.id == receipt_id,
        PostbackReceipt.endpoint_id == endpoint_id).with_for_update())
    if not receipt or receipt.status not in {"unmatched", "ambiguous", "invalid"}:
        raise HTTPException(409, "Only unmatched, ambiguous or invalid receipts can be reprocessed")
    previous = {"at": now().isoformat(), "actor_id": str(current_user.id), "status": receipt.status,
        "reason": receipt.error_message, "revision": receipt.endpoint_revision}
    if not use_current_contract and receipt.endpoint_revision and receipt.endpoint_revision != endpoint.revision:
        raise HTTPException(409, "Contract changed; explicitly select the current contract for reprocessing")
    receipt.attempt_log = [*(receipt.attempt_log or []), previous]
    result = await PostbackContractService(db).receive(token=endpoint.secret_token, method=receipt.request_method,
        query=receipt.query_payload, body=receipt.body_payload, received_at=receipt.received_at, receipt=receipt)
    await db.execute(update(PostbackRelayDelivery).where(PostbackRelayDelivery.project_id == project_id,
        PostbackRelayDelivery.response_json["receipt_id"].astext == str(receipt_id)).values(response_json=result.model_dump(mode="json")))
    return result


@router.get("", response_model=list[PostbackEndpointOut])
async def list_postback_endpoints(
    partner_integration_id: UUID | None = Query(default=None),
    include_archived: bool = Query(default=False),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PostbackEndpointOut]:
    return await PostbackEndpointService(db).list_endpoints(
        project_id=project_id,
        actor=current_user,
        partner_integration_id=partner_integration_id,
        include_archived=include_archived,
    )


@router.post("", response_model=PostbackEndpointOut, status_code=status.HTTP_201_CREATED)
async def create_postback_endpoint(
    data: PostbackEndpointCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostbackEndpointOut:
    return await PostbackEndpointService(db).create_endpoint(
        project_id=project_id,
        actor=current_user,
        data=data,
    )


@router.patch("/{endpoint_id}", response_model=PostbackEndpointOut)
async def update_postback_endpoint(
    endpoint_id: UUID,
    data: PostbackEndpointUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostbackEndpointOut:
    return await PostbackEndpointService(db).update_endpoint(
        endpoint_id=endpoint_id,
        project_id=project_id,
        actor=current_user,
        data=data,
    )


@router.post("/{endpoint_id}/rotate-secret", response_model=PostbackEndpointOut)
async def rotate_postback_secret(
    endpoint_id: UUID,
    revoke_old: bool = Query(default=False),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostbackEndpointOut:
    return await PostbackEndpointService(db).rotate_secret(
        endpoint_id=endpoint_id,
        project_id=project_id,
        actor=current_user,
        revoke_old=revoke_old,
    )


@router.delete(
    "/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
async def delete_postback_endpoint(
    endpoint_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await PostbackEndpointService(db).delete_endpoint(
        endpoint_id=endpoint_id,
        project_id=project_id,
        actor=current_user,
    )


@router.get("/{endpoint_id}/receipts", response_model=list[PostbackReceiptOut])
async def list_postback_receipts(
    endpoint_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PostbackReceiptOut]:
    return [
        PostbackReceiptOut.model_validate(receipt)
        for receipt in await PostbackEndpointService(db).list_receipts(
            endpoint_id=endpoint_id,
            project_id=project_id,
            actor=current_user,
            limit=limit,
        )
    ]


@lead_event_router.post("/{lead_id}/events", response_model=LeadEventOut)
async def create_manual_lead_event(
    lead_id: UUID,
    data: LeadEventCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadEventOut:
    if data.offer_id is not None:
        from app.services.gambling_offer_service import GamblingOfferService
        event = await GamblingOfferService(db).manual_event(project_id, current_user, lead_id, data)
        return LeadEventOut.model_validate(event)
    event = await LeadEventService(db).record_manual_event(
        lead_id=lead_id,
        project_id=project_id,
        actor=current_user,
        event_type=data.event_type,
        amount=data.amount,
        currency=data.currency,
        partner_integration_id=data.partner_integration_id,
        external_event_id=data.external_event_id,
        payload=data.payload,
        occurred_at=data.occurred_at,
    )
    return LeadEventOut.model_validate(event)


@public_router.api_route(
    "/{secret_token}",
    methods=["GET", "POST"],
    response_model=PublicPostbackResult,
)
async def receive_public_postback(
    secret_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PublicPostbackResult:
    from app.core.config import settings
    from fastapi import HTTPException
    if not settings.POSTBACK_DIRECT_ENABLED:
        raise HTTPException(404)
    if len(request.scope.get("query_string", b"")) > 8192 or len(request.query_params.multi_items()) > 100:
        raise HTTPException(413)
    body_payload = await _request_payload(request)
    try:
        result = await PostbackEndpointService(db).receive(
            secret_token=secret_token, request_method=request.method,
            query_payload=dict(request.query_params), body_payload=body_payload)
        from app.models.postback import PostbackReceipt, PostbackEndpointRevision
        from fastapi.responses import PlainTextResponse
        receipt = await db.get(PostbackReceipt, result.receipt_id)
        revision = await db.get(PostbackEndpointRevision, (receipt.endpoint_id, receipt.endpoint_revision))
        ack = (revision.config_json.get("parameter_mapping") or {}).get("ack_text") if revision else None
        await db.commit()
        return PlainTextResponse(ack) if isinstance(ack, str) else result
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Direct postback failed type=%s", type(exc).__name__)
        raise HTTPException(503, "Postback temporarily unavailable") from None


async def _request_payload(request: Request) -> dict[str, Any]:
    from fastapi import HTTPException
    if request.method == "GET":
        return {}
    raw = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise HTTPException(413)
    except TimeoutError:
        raise HTTPException(408) from None
    if not raw:
        return {}
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    try:
        if content_type == "application/json":
            value = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value
        if content_type == "application/x-www-form-urlencoded":
            return dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=100))
        if content_type == "multipart/form-data":
            from starlette.formparsers import MultiPartParser, MultiPartException
            async def stream():
                yield bytes(raw)
            try:
                return dict(await MultiPartParser(request.headers, stream(), max_files=0, max_fields=100).parse())
            except MultiPartException:
                raise ValueError("Invalid multipart fields") from None
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "Invalid postback payload") from None
    raise HTTPException(415, "Unsupported postback content type")
