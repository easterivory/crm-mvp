from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import text
import logging
from app.api.v1.dependencies import get_db
from app.services.postback_relay_service import authenticate, manifest, deliver, RelayEnvelope

router = APIRouter(prefix="/internal/postback-relay", include_in_schema=False)
logger = logging.getLogger(__name__)


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
