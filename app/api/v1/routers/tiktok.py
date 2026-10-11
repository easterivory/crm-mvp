from uuid import UUID
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.core.tiktok_events import default_tiktok_mappings, normalize_tiktok_mappings
from app.models.tracking import TrackingLink
from app.models.tiktok import TikTokDelivery, TikTokIntegration
from app.models.user import User
from app.services.ai_credential_service import AICredentialService
from app.services.facebook_campaign_service import FacebookCampaignService

router = APIRouter(prefix="/tracking/links", tags=["TikTok"])


class TikTokSettings(BaseModel):
    enabled: bool = False
    pixel_id: str = Field(default="", max_length=120)
    access_token: str | None = Field(default=None, max_length=4096)
    clear_token: bool = False
    test_event_code: str | None = Field(default=None, max_length=100)
    mappings: list[dict] = Field(default_factory=default_tiktok_mappings, max_length=20)

    @field_validator("mappings")
    @classmethod
    def validate_mappings(cls, value):
        return normalize_tiktok_mappings(value)

    @field_validator("pixel_id", "test_event_code")
    @classmethod
    def validate_identifier(cls, value):
        value = (value or "").strip()
        if value and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("TikTok identifier contains unsupported characters")
        return value

    @field_validator("access_token")
    @classmethod
    def validate_token(cls, value):
        value = (value or "").strip()
        if any(char.isspace() for char in value):
            raise ValueError("Access Token must not contain whitespace")
        return value or None


async def scoped_link(db: AsyncSession, link_id: UUID, project_id: UUID, user: User) -> TrackingLink:
    if user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN, RoleName.BUYER}:
        raise HTTPException(403, "TikTok settings require admin or buyer access")
    link = await db.scalar(select(TrackingLink).where(TrackingLink.id == link_id, TrackingLink.project_id == project_id))
    if link is None or (user.role_name == RoleName.BUYER and link.buyer_id != user.id):
        raise HTTPException(404, "Tracking link not found")
    return link


def read_config(config: TikTokIntegration | None) -> dict:
    return {"enabled": config.enabled if config else False, "pixel_id": config.pixel_id if config else "",
            "has_token": bool(config and config.encrypted_token), "test_event_code": config.test_event_code if config else None,
            "mappings": config.mappings_json if config else default_tiktok_mappings()}


@router.get("/{link_id}/tiktok")
async def get_settings(link_id: UUID, project_id: UUID = Depends(get_current_project_id),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await scoped_link(db, link_id, project_id, user)
    return read_config(await db.get(TikTokIntegration, link_id))


@router.put("/{link_id}/tiktok")
async def save_settings(link_id: UUID, data: TikTokSettings, project_id: UUID = Depends(get_current_project_id),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await scoped_link(db, link_id, project_id, user)
    # Lock the parent as well: concurrent first saves have no config row yet.
    await db.execute(select(TrackingLink.id).where(TrackingLink.id == link_id).with_for_update())
    try:
        await FacebookCampaignService(db).validate_mapping_triggers(project_id=project_id, mappings=data.mappings)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    config = await db.scalar(select(TikTokIntegration).where(TikTokIntegration.tracking_link_id == link_id).with_for_update())
    token = data.access_token.strip() if data.access_token else None
    encrypted = AICredentialService().encrypt(token) if token else None if data.clear_token else config.encrypted_token if config else None
    if data.enabled and (not data.pixel_id or not encrypted):
        raise HTTPException(422, "Укажите TikTok Pixel ID и Access Token.")
    if config is None:
        config = TikTokIntegration(tracking_link_id=link_id)
        db.add(config)
    config.enabled, config.pixel_id, config.encrypted_token = data.enabled, data.pixel_id, encrypted
    config.test_event_code, config.mappings_json = data.test_event_code or None, data.mappings
    await db.flush()
    return read_config(config)


@router.get("/{link_id}/tiktok/deliveries")
async def deliveries(link_id: UUID, project_id: UUID = Depends(get_current_project_id),
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await scoped_link(db, link_id, project_id, user)
    items = (await db.scalars(select(TikTokDelivery).where(TikTokDelivery.tracking_link_id == link_id)
                             .order_by(TikTokDelivery.created_at.desc()).limit(50))).all()
    return [{"id": str(i.id), "source_event": i.source_event, "event_name": i.payload_json["data"][0]["event"],
             "status": i.status, "attempts": i.attempts, "error": i.last_error, "request_id": i.request_id,
             "has_click_id": bool(i.payload_json["data"][0].get("user", {}).get("ttclid")),
             "created_at": i.created_at} for i in items]


@router.post("/{link_id}/tiktok/deliveries/{delivery_id}/retry")
async def retry_delivery(link_id: UUID, delivery_id: UUID, project_id: UUID = Depends(get_current_project_id),
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    await scoped_link(db, link_id, project_id, user)
    config = await db.get(TikTokIntegration, link_id)
    if not config or not config.enabled:
        raise HTTPException(422, "Сначала включите интеграцию TikTok.")
    item = await db.scalar(select(TikTokDelivery).where(TikTokDelivery.id == delivery_id,
                           TikTokDelivery.tracking_link_id == link_id).with_for_update())
    if not item:
        raise HTTPException(404, "Event not found")
    if item.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "Event is already sent or queued")
    if datetime.now(timezone.utc).timestamp() - item.payload_json["data"][0]["event_time"] > 7 * 86400:
        raise HTTPException(422, "Событие старше 7 дней; нельзя менять фактическое время конверсии.")
    item.status, item.attempts, item.next_attempt_at = "pending", 0, datetime.now(timezone.utc)
    item.payload_json = {**item.payload_json, "event_source_id": config.pixel_id}
    if config.test_event_code:
        item.payload_json = {**item.payload_json, "test_event_code": config.test_event_code}
    else:
        item.payload_json = {k: v for k, v in item.payload_json.items() if k != "test_event_code"}
    return {"queued": True}
