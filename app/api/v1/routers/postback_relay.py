from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import text
import logging
from app.api.v1.dependencies import get_db
from app.services.postback_relay_service import authenticate, manifest, deliver, RelayEnvelope

router = APIRouter(prefix="/internal/postback-relay", include_in_schema=False)
logger = logging.getLogger(__name__)


@router.post("/heartbeat")
async def heartbeat(request: Request, db=Depends(get_db)):
    from datetime import datetime, timezone
    from uuid import UUID
    from pydantic import BaseModel, Field, ConfigDict
    from sqlalchemy.dialects.postgresql import insert
    from app.models.postback import PostbackRelayHealth
    from typing import Literal
    class Heartbeat(BaseModel):
        model_config = ConfigDict(extra="forbid")
        instance_id: UUID
        counts: dict[Literal["pending", "sending", "done", "dead"], int] = Field(max_length=4)
        oldest_pending_seconds: float = Field(ge=0)
        manifest_age_seconds: float | None = Field(default=None, ge=0)
        free_bytes: int = Field(ge=0)
    body = await authenticate(request)
    try:
        data = Heartbeat.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Invalid heartbeat") from None
    await db.execute(insert(PostbackRelayHealth).values(instance_id=data.instance_id,
        seen_at=datetime.now(timezone.utc), stats_json=data.model_dump(mode="json"))
        .on_conflict_do_update(index_elements=[PostbackRelayHealth.instance_id],
            set_={"seen_at": datetime.now(timezone.utc), "stats_json": data.model_dump(mode="json")}))
    return {"status": "ok"}


@router.get("/manifest")
async def get_manifest(request: Request, db=Depends(get_db)):
    await authenticate(request)
    try:
        return await manifest(db)
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Postback manifest failed type=%s", type(exc).__name__)
        raise HTTPException(503, "Relay temporarily unavailable") from None


@router.post("/deliver")
async def receive(request: Request, db=Depends(get_db)):
    body = await authenticate(request)
    try:
        envelope = RelayEnvelope.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Invalid relay envelope") from None
    try:
        await db.execute(text("SET LOCAL lock_timeout = '5s'"))
        result = await deliver(db, envelope, body)
        # A successful HTTP response must never precede durable business + dedup commit.
        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        # SQL exception strings can include endpoint secrets and partner payloads.
        logger.error("Postback relay failed delivery_id=%s type=%s", envelope.delivery_id, type(exc).__name__)
        raise HTTPException(503, "Relay temporarily unavailable") from None
    return {"delivery_id": str(envelope.delivery_id), "result": result}
