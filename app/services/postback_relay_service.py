"""Optional signed relay. Business matching stays in PostbackEndpointService."""
import hashlib
import hmac
import time
import re
from urllib.parse import urlsplit
from uuid import UUID
from datetime import datetime

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    received_at: datetime | None = None
    endpoint_id: UUID | None = None
    endpoint_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_metadata(self):
        if (self.endpoint_id is None) != (self.endpoint_revision is None):
            raise ValueError("Endpoint ID and revision must be provided together")
        if self.received_at is not None and self.received_at.tzinfo is None:
            raise ValueError("received_at must include timezone")
        return self


async def manifest(db):
    stmt = select(PostbackEndpoint).join(Project, Project.id == PostbackEndpoint.project_id).where(
        PostbackEndpoint.is_active.is_(True), PostbackEndpoint.is_archived.is_(False), Project.is_deleted.is_(False), Project.status == "active")
    scope = project_scope()
    if scope is not None:
        stmt = stmt.where(PostbackEndpoint.project_id.in_(scope))
    from app.services.postback_contract_service import snapshot, now
    from app.models.postback import PostbackEndpointRevision
    endpoints = (await db.scalars(stmt)).all()
    entries = []
    for endpoint in endpoints:
        await snapshot(db, endpoint)
        entries.append({"token_hash": hashlib.sha256(endpoint.secret_token.encode()).hexdigest(),
            "endpoint_id": str(endpoint.id), "revision": endpoint.revision,
            "ack_text": (endpoint.parameter_mapping or {}).get("ack_text")})
        old = (await db.scalars(select(PostbackEndpointRevision).where(PostbackEndpointRevision.endpoint_id == endpoint.id,
            PostbackEndpointRevision.revoked.is_(False),
            PostbackEndpointRevision.valid_until > now()).order_by(PostbackEndpointRevision.revision.desc()))).all()
        seen = {entry["token_hash"] for entry in entries}
        for revision in old:
            if revision.token_hash not in seen:
                entries.append({"token_hash": revision.token_hash, "endpoint_id": str(endpoint.id), "revision": revision.revision,
                    "ack_text": (revision.config_json.get("parameter_mapping") or {}).get("ack_text")})
                seen.add(revision.token_hash)
    # V1 clients continue to work; upgraded gateways persist the optional contract metadata.
    return {"version": 1, "protocol_version": 2, "token_hashes": [e["token_hash"] for e in entries], "endpoints": entries}


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
    from app.services.postback_contract_service import PostbackContractService
    endpoint, _, _ = await PostbackContractService(db).endpoint(envelope.secret_token,
        endpoint_id=envelope.endpoint_id, revision=envelope.endpoint_revision, received_at=envelope.received_at)
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
        request_method=envelope.request_method, query_payload=envelope.query_payload, body_payload=envelope.body_payload,
        received_at=envelope.received_at, endpoint_id=envelope.endpoint_id, revision=envelope.endpoint_revision)
    row = await db.get(PostbackRelayDelivery, envelope.delivery_id)
    row.response_json = result.model_dump(mode="json")
    await db.flush()
    return row.response_json
