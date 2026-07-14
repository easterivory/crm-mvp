import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_access_token
from app.core.telegram_links import build_telegram_bot_start_link
from app.repositories.user_repository import UserRepository
from app.schemas.user import TokenOut
from app.services.auth_service import AuthService
from app.services.admin_bot_service import AdminTelegramClient
from app.services.system_setting_service import SystemSettingService
from app.services.telegram_login_service import (
    LOGIN_SESSION_TTL_SECONDS,
    TelegramLoginSessionService,
)


router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class TelegramLoginConfigOut(BaseModel):
    username: str | None
    is_configured: bool


class TelegramLoginSessionOut(BaseModel):
    session_token: str
    deep_link: str
    bot_username: str
    expires_in: int


class TelegramLoginSessionStatusIn(BaseModel):
    session_token: str


class TelegramLoginSessionStatusOut(BaseModel):
    status: str
    access_token: str | None = None


@router.get("/telegram-config", response_model=TelegramLoginConfigOut)
async def telegram_login_config(
    db: AsyncSession = Depends(get_db),
) -> TelegramLoginConfigOut:
    token = (await SystemSettingService(db).get_effective_global_config()).admin_bot_token
    if not token:
        return TelegramLoginConfigOut(username=None, is_configured=False)
    try:
        username = await _admin_bot_username(token)
    except Exception:
        logger.exception("Could not resolve admin bot username for Telegram login")
        return TelegramLoginConfigOut(username=None, is_configured=False)
    return TelegramLoginConfigOut(
        username=username,
        is_configured=bool(username),
    )


@router.post("/telegram-login/sessions", response_model=TelegramLoginSessionOut)
async def create_telegram_login_session(
    db: AsyncSession = Depends(get_db),
) -> TelegramLoginSessionOut:
    token = (await SystemSettingService(db).get_effective_global_config()).admin_bot_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin Telegram bot is not configured",
        )
    try:
        username = await _admin_bot_username(token)
    except Exception as exc:
        logger.exception("Could not resolve admin bot username for Telegram login session")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Admin Telegram bot token is invalid or Telegram API is unavailable",
        ) from exc

    sessions = TelegramLoginSessionService()
    token = await sessions.create()
    argument = sessions.start_argument(token)
    return TelegramLoginSessionOut(
        session_token=token,
        deep_link=build_telegram_bot_start_link(username, argument),
        bot_username=username,
        expires_in=LOGIN_SESSION_TTL_SECONDS,
    )


@router.post(
    "/telegram-login/sessions/status",
    response_model=TelegramLoginSessionStatusOut,
)
async def telegram_login_session_status(
    data: TelegramLoginSessionStatusIn,
    db: AsyncSession = Depends(get_db),
) -> TelegramLoginSessionStatusOut:
    sessions = TelegramLoginSessionService()
    login_session = await sessions.get(data.session_token)
    if login_session is None:
        return TelegramLoginSessionStatusOut(status="expired")
    if login_session.status != "approved" or login_session.telegram_id is None:
        return TelegramLoginSessionStatusOut(status="pending")

    user = await UserRepository(db).get_by_telegram_id(login_session.telegram_id)
    if user is None or user.is_deleted:
        await sessions.consume(data.session_token)
        return TelegramLoginSessionStatusOut(status="not_registered")

    consumed = await sessions.consume(data.session_token)
    if consumed is None or consumed.telegram_id != login_session.telegram_id:
        return TelegramLoginSessionStatusOut(status="expired")
    return TelegramLoginSessionStatusOut(
        status="completed",
        access_token=create_access_token(subject=user.id),
    )


@router.post("/telegram-login", response_model=TokenOut)
async def telegram_login(
    auth_data: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    token = (await SystemSettingService(db).get_effective_global_config()).admin_bot_token
    if not token or not AuthService.verify_telegram_auth(
        auth_data,
        bot_token=token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram signature",
        )

    telegram_id = _extract_telegram_id(auth_data)
    if telegram_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telegram ID is missing",
        )

    user = await UserRepository(db).get_by_telegram_id(telegram_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with this Telegram account is not registered in CRM",
        )

    return TokenOut(access_token=create_access_token(subject=user.id))


async def _admin_bot_username(token: str) -> str:
    client = AdminTelegramClient(token)
    try:
        profile = await client.get_me()
    finally:
        await client.close()
    username = str(profile.get("username") or "").removeprefix("@").strip()
    if not username:
        raise RuntimeError("Admin bot does not have a username")
    return username


def _extract_telegram_id(auth_data: dict[str, Any]) -> int | None:
    raw_id = auth_data.get("id")
    raw_user = auth_data.get("user")
    if raw_id is None and isinstance(raw_user, str):
        try:
            raw_user = json.loads(raw_user)
        except json.JSONDecodeError:
            raw_user = None
    if raw_id is None and isinstance(raw_user, dict):
        raw_id = raw_user.get("id")
    if raw_id is None:
        return None
    try:
        telegram_id = int(str(raw_id))
    except (TypeError, ValueError):
        return None
    return telegram_id if telegram_id > 0 else None
