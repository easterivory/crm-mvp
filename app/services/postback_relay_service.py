"""Optional signed relay. Business matching stays in PostbackEndpointService."""
import hashlib
import hmac
import time
import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.models.postback import PostbackEndpoint, PostbackRelayDelivery
from app.models.project import Project

MAX_RELAY_BODY = 262144


def signature(secret, method, path, timestamp, body):
    message = f"{method}\n{path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def public_base_url():
    value = settings.POSTBACK_PUBLIC_BASE_URL.strip().rstrip("/")
    if not value or not settings.POSTBACK_RELAY_ENABLED:
        return settings.BASE_URL.rstrip("/")
    if len(settings.POSTBACK_RELAY_SECRET) < 32:
        raise HTTPException(503, "Configure POSTBACK_RELAY_SECRET before publishing relay URLs")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise HTTPException(503, "Invalid POSTBACK_PUBLIC_BASE_URL") from None
    if any(c.isspace() for c in value):
        raise HTTPException(503, "Invalid POSTBACK_PUBLIC_BASE_URL")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, "Invalid POSTBACK_PUBLIC_BASE_URL: HTTPS origin required")
    return value


def project_scope():
    value = settings.POSTBACK_RELAY_PROJECT_IDS.strip()
    if value == "*":
        return None
    try:
        return {UUID(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError:
        raise HTTPException(503, "Invalid relay project scope") from None


async def authenticate(request: Request):
    secret = settings.POSTBACK_RELAY_SECRET
    if not settings.POSTBACK_RELAY_ENABLED or len(secret) < 32:
        raise HTTPException(404)
    timestamp = request.headers.get("x-relay-timestamp", "")
    supplied = request.headers.get("x-relay-signature", "")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        raise HTTPException(401, "Invalid relay authentication")
    try:
        if abs(time.time() - int(timestamp)) > 60:
            raise ValueError()
    except ValueError:
        raise HTTPException(401, "Invalid relay authentication") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_RELAY_BODY:
            raise HTTPException(413)
    if request.url.query or not hmac.compare_digest(supplied, signature(secret, request.method, request.url.path, timestamp, bytes(body))):
        raise HTTPException(401, "Invalid relay authentication")
    return bytes(body)


class RelayEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_id: UUID
    secret_token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    request_method: Literal["GET", "POST"]
    query_payload: dict[str, Any]
    body_payload: dict[str, Any]


async def manifest(db):
    stmt = select(PostbackEndpoint.secret_token).join(Project, Project.id == PostbackEndpoint.project_id).where(
        PostbackEndpoint.is_active.is_(True), Project.is_deleted.is_(False), Project.status == "active")
    scope = project_scope()
    if scope is not None:
        stmt = stmt.where(PostbackEndpoint.project_id.in_(scope))
    tokens = (await db.scalars(stmt)).all()
    return {"version": 1, "token_hashes": [hashlib.sha256(t.encode()).hexdigest() for t in tokens]}


async def deliver(db, envelope: RelayEnvelope, body: bytes):
    from app.services.postback_endpoint_service import PostbackEndpointService
    digest = hashlib.sha256(body).hexdigest()
    scope = project_scope()
    existing = await db.get(PostbackRelayDelivery, envelope.delivery_id)
    if existing:
        if scope is not None and existing.project_id not in scope:
            raise HTTPException(403)
        if existing.payload_hash != digest:
            raise HTTPException(409, "Delivery ID reused with different payload")
        return existing.response_json
    endpoint = await db.scalar(select(PostbackEndpoint).join(Project, Project.id == PostbackEndpoint.project_id).where(
        PostbackEndpoint.secret_token == envelope.secret_token, PostbackEndpoint.is_active.is_(True),
        Project.is_deleted.is_(False), Project.status == "active"))
    if endpoint is None or (scope is not None and endpoint.project_id not in scope):
        raise HTTPException(404)
    claimed = await db.scalar(insert(PostbackRelayDelivery).values(id=envelope.delivery_id,
        project_id=endpoint.project_id, payload_hash=digest, response_json={})
        .on_conflict_do_nothing().returning(PostbackRelayDelivery.id))
    if not claimed:
        existing = await db.get(PostbackRelayDelivery, envelope.delivery_id, populate_existing=True)
        if existing.project_id != endpoint.project_id or existing.payload_hash != digest:
            raise HTTPException(409, "Delivery ID reused with different payload")
        return existing.response_json
    result = await PostbackEndpointService(db).receive(secret_token=envelope.secret_token,
        request_method=envelope.request_method, query_payload=envelope.query_payload, body_payload=envelope.body_payload)
    row = await db.get(PostbackRelayDelivery, envelope.delivery_id)
    row.response_json = result.model_dump(mode="json")
    await db.flush()
    return row.response_json
