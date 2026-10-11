"""Transactional outbox: commit claims before any external network operation."""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select, update

from app.core.database import get_db_session
from app.models.tiktok import TikTokDelivery, TikTokIntegration
from app.services.ai_credential_service import AICredentialService

logger = logging.getLogger(__name__)
TIKTOK_EVENTS_URL = "https://business-api.tiktok.com/open_api/v1.3/event/track/"


async def deliver_tiktok_outbox_task(ctx: dict) -> dict:
    sent = 0
    deadline = time.monotonic() + 20
    for _ in range(50):
        if time.monotonic() >= deadline:
            break
        now = datetime.now(timezone.utc)
        async with get_db_session() as db:
            item = await db.scalar(select(TikTokDelivery).where(
                TikTokDelivery.status.in_(["pending", "retry", "sending"]),
                TikTokDelivery.next_attempt_at <= now,
            ).order_by(TikTokDelivery.next_attempt_at).with_for_update(skip_locked=True).limit(1))
            if item is None:
                break
            config = await db.get(TikTokIntegration, item.tracking_link_id)
            if config is None or not config.enabled:
                item.status = "cancelled"
                await db.commit()
                continue
            item_id, payload, encrypted_token = item.id, dict(item.payload_json), config.encrypted_token
            item.attempts += 1
            attempt = item.attempts
            item.status = "sending"
            item.next_attempt_at = now + timedelta(minutes=3)
            await db.commit()

        retryable, error, request_id = False, None, None
        try:
            if now.timestamp() - payload["data"][0]["event_time"] > 7 * 86400:
                raise ValueError("Event expired")
            token = AICredentialService().decrypt(encrypted_token)
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
                response = await client.post(TIKTOK_EVENTS_URL, headers={"Access-Token": token}, json=payload)
            retryable = response.status_code == 429 or response.status_code >= 500
            if response.status_code != 200:
                error = f"TikTok HTTP {response.status_code}"
            else:
                try:
                    result = response.json()
                except ValueError:
                    result = {}
                    retryable = True
                if not isinstance(result, dict) or result.get("code") != 0:
                    code = result.get("code") if isinstance(result, dict) else None
                    error = f"TikTok rejected event (code={code})" if code is not None else "TikTok returned an unreadable response"
                    message = str(result.get("message", "")).lower() if isinstance(result, dict) else ""
                    retryable = retryable or any(marker in message for marker in (
                        "too frequent", "rate limit", "too many requests", "temporarily", "internal server", "system error",
                    ))
                else:
                    request_id = str(result.get("request_id") or "")[:100]
        except httpx.HTTPError:
            retryable, error = True, "TikTok network timeout or connection failure"
        except ValueError:
            error = "TikTok event is older than 7 days; original event time was preserved"
        except Exception:
            error = "TikTok credentials could not be decrypted; check the server encryption key"
        status = "sent" if error is None else "retry" if retryable and attempt < 8 else "failed"
        async with get_db_session() as db:
            await db.execute(update(TikTokDelivery).where(TikTokDelivery.id == item_id,
                             TikTokDelivery.attempts == attempt, TikTokDelivery.status == "sending").values(
                status=status, last_error=error, request_id=request_id,
                next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=min(30 * 2 ** (attempt - 1), 3600))))
            await db.commit()
        if error:
            logger.warning("TikTok delivery event_id=%s attempt=%s status=%s error=%s", item_id, attempt, status, error)
        else:
            sent += 1
    async with get_db_session() as db:
        expired_ids = select(TikTokDelivery.id).where(
            TikTokDelivery.created_at < datetime.now(timezone.utc) - timedelta(days=30),
        ).order_by(TikTokDelivery.created_at).limit(500)
        await db.execute(delete(TikTokDelivery).where(TikTokDelivery.id.in_(expired_ids)))
        await db.commit()
    return {"sent": sent}
