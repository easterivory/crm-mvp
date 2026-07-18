from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.postback import (
    LeadEventCreate,
    LeadEventOut,
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


@router.get("", response_model=list[PostbackEndpointOut])
async def list_postback_endpoints(
    partner_integration_id: UUID | None = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PostbackEndpointOut]:
    return await PostbackEndpointService(db).list_endpoints(
        project_id=project_id,
        actor=current_user,
        partner_integration_id=partner_integration_id,
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
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostbackEndpointOut:
    return await PostbackEndpointService(db).rotate_secret(
        endpoint_id=endpoint_id,
        project_id=project_id,
        actor=current_user,
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
    body_payload = await _request_payload(request)
    return await PostbackEndpointService(db).receive(
        secret_token=secret_token,
        request_method=request.method,
        query_payload=dict(request.query_params),
        body_payload=body_payload,
    )


async def _request_payload(request: Request) -> dict[str, Any]:
    if request.method == "GET":
        return {}
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {"payload": payload}
    try:
        form = await request.form()
    except Exception:
        return {}
    return {key: value for key, value in form.items()}
