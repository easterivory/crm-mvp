"""
POST /api/v1/telegram/webhook/{bot_id} — receives Telegram Bot API updates.

Security model:
  - bot_id is taken from the webhook path generated during bot registration.
    project_id is resolved from that bot row; it is never accepted from the
    request body or query string.
  - Optional secret-token validation via X-Telegram-Bot-Api-Secret-Token header.
    If TELEGRAM_WEBHOOK_SECRET is set, requests without the matching header
    are rejected with 403. If the setting is absent, the header is ignored.

HTTP response contract:
  - 200  must be returned for all successfully processed updates (even if the
         update contains no message, or the message was silently discarded).
         Returning non-200 causes Telegram to retry the same update repeatedly.
  - 400  for malformed JSON that cannot be parsed into a TelegramUpdate.
         Telegram does NOT retry 4xx, so this is safe for genuine parse errors.
  - 403  when the secret token header is present but incorrect.
         Telegram does not retry 4xx; rejects future deliveries until fixed.
  - Unexpected exceptions are caught, logged as ERROR, and still return 200
         so Telegram does not spam retries for a transient server error.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import settings
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook/{bot_id}", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    bot_id: UUID,
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    """
    Receives a Telegram Bot API Update payload and processes it.

    Only `message` updates are handled. All other update types are silently
    ignored and a {"ok": True} response is returned immediately.

    No replies, GPT calls, or alerts are generated here.
    """
    # ── Optional secret token validation ──────────────────────────────────────
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning(
                "Telegram webhook: invalid or missing secret token from %s",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook secret token",
            )

    # ── Parse payload ──────────────────────────────────────────────────────────
    try:
        payload = await request.json()
    except Exception:
        # Truly unparseable body — Telegram should not retry 4xx
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not valid JSON",
        )

    update = TelegramService.parse_update(payload)
    if update is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body does not match expected Telegram Update schema",
        )

    # ── Process update inside a managed DB session ─────────────────────────────
    # We open the session manually (not via Depends) because we must catch
    # exceptions from the service layer and still return 200 to Telegram.
    from app.core.database import get_db_session  # local import — avoids circular
    from app.repositories.bot_repository import BotRepository

    try:
        async with get_db_session() as db:
            try:
                bot = await BotRepository(db).get_active(bot_id)
                if bot is None:
                    logger.warning(
                        "Telegram webhook: unknown bot_id=%s update_id=%s",
                        bot_id,
                        update.update_id,
                    )
                    return {"ok": True}

                await TelegramService(db).handle_update(
                    update=update,
                    project_id=bot.project_id,
                    bot_id=bot.id,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    except Exception:
        # Log the full traceback but do NOT propagate — returning 200 prevents
        # Telegram from queuing the same update for repeated delivery.
        logger.exception(
            "Unexpected error processing Telegram update_id=%s bot_id=%s",
            update.update_id,
            bot_id,
        )

    return {"ok": True}
