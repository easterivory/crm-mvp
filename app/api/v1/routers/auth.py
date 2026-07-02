import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_access_token
from app.repositories.user_repository import UserRepository
from app.schemas.user import TokenOut
from app.services.auth_service import AuthService
from app.services.system_setting_service import SystemSettingService
from app.services.telegram_login_service import (
    LOGIN_SESSION_TTL_SECONDS,
    TelegramLoginSessionService,
)


router = APIRouter(prefix="/auth", tags=["auth"])


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
    config = await SystemSettingService(db).get_effective_buyer_bot_config()
    return TelegramLoginConfigOut(
        username=config.username,
        is_configured=bool(config.username and config.token),
    )


@router.post("/telegram-login/sessions", response_model=TelegramLoginSessionOut)
async def create_telegram_login_session(
    db: AsyncSession = Depends(get_db),
) -> TelegramLoginSessionOut:
    config = await SystemSettingService(db).get_effective_buyer_bot_config()
    username = (config.username or "").removeprefix("@").strip()
    if not config.token or not username:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram login bot is not configured",
        )

    sessions = TelegramLoginSessionService()
    token = await sessions.create()
    argument = sessions.start_argument(token)
    return TelegramLoginSessionOut(
        session_token=token,
        deep_link=f"https://t.me/{quote(username)}?start={quote(argument)}",
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
    config = await SystemSettingService(db).get_effective_buyer_bot_config()
    if not config.token or not AuthService.verify_telegram_auth(
        auth_data,
        bot_token=config.token,
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
