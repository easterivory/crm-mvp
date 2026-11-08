"""Shared draft-only offer assignment validation, independent of API transport."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models.funnel import Funnel, FunnelVersion
from app.models.gambling_offer import GamblingOffer
from app.services.access_control import require_project_access
from app.services.funnel_service import FunnelService
from app.services.gambling_offer_service import GamblingOfferService


async def get_draft_offer_assignment(db, project_id, version_id, offer_id, actor):
    require_project_access(actor, project_id)
    FunnelService._ensure_write_allowed(actor)
    row = await db.scalar(select(FunnelVersion).join(Funnel, Funnel.id == FunnelVersion.funnel_id).where(
        FunnelVersion.id == version_id, Funnel.project_id == project_id).with_for_update(of=FunnelVersion))
    if row is None: raise HTTPException(404)
    if row.status != "draft": raise HTTPException(409, "Оффер меняется только у черновика версии")
    offer = None
    if offer_id:
        await GamblingOfferService(db).project(project_id)
        offer = await db.get(GamblingOffer, offer_id)
        if not offer or offer.project_id != project_id or not offer.is_active:
            raise HTTPException(422, "Выберите действующий оффер проекта")
    return row, offer
