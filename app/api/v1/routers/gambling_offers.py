from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models import Lead, User
from app.models.funnel import Funnel, FunnelVersion
from app.models.gambling_offer import GamblingOffer
from app.models.lead_event import LeadEvent
from app.models.postback import PostbackEndpoint
from app.schemas.gambling_offer import OfferWrite, PayoutPolicyWrite, QualificationWrite, FunnelOfferWrite
from app.services.access_control import require_project_access
from app.services.gambling_offer_service import GamblingOfferService, manage_access
from app.services.offer_payout_service import OfferPayoutService

router = APIRouter(prefix="/gambling-offers", tags=["gambling-offers"])


@router.get("")
async def offers(project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await GamblingOfferService(db).list_offers(project_id, actor)


@router.post("")
async def create(data: OfferWrite, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await GamblingOfferService(db).save(project_id, actor, data)


@router.get("/payout-policies")
async def policies(project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await OfferPayoutService(db).policies(project_id, actor)


@router.post("/payout-policies")
async def create_policy(data: PayoutPolicyWrite, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await OfferPayoutService(db).save_policy(project_id, actor, data)


@router.put("/payout-policies/{policy_id}")
async def update_policy(policy_id: UUID, data: PayoutPolicyWrite, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await OfferPayoutService(db).save_policy(project_id, actor, data, policy_id)


@router.get("/finance")
async def finance(day: date, policy_id: UUID | None = None, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await OfferPayoutService(db).report(project_id, actor, day, policy_id)


@router.get("/qualification")
async def pending(project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await OfferPayoutService(db).pending(project_id, actor)


@router.get("/coverage")
async def coverage(bot_id: UUID | None = None, link_id: UUID | None = None,
    project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.models import Bot, TrackingLink
    from app.models.gambling_offer import OfferLink
    require_project_access(actor, project_id)
    if link_id:
        source = await db.scalar(select(TrackingLink).where(TrackingLink.id == link_id, TrackingLink.project_id == project_id))
        if not source or bot_id and bot_id != source.bot_id: raise HTTPException(404)
        bot_id = source.bot_id
    planned = select(FunnelVersion.id).join(Bot, Bot.active_funnel_version_id == FunnelVersion.id).join(
        GamblingOffer, GamblingOffer.id == FunnelVersion.offer_id).outerjoin(PostbackEndpoint, PostbackEndpoint.id == GamblingOffer.endpoint_id).where(
        Bot.project_id == project_id, Bot.is_deleted.is_(False), or_(GamblingOffer.postbacks_enabled.is_(False),
        PostbackEndpoint.id.is_(None), PostbackEndpoint.is_active.is_(False), PostbackEndpoint.is_archived.is_(True)))
    issued = select(OfferLink.id).outerjoin(PostbackEndpoint, PostbackEndpoint.id == OfferLink.endpoint_id).where(
        OfferLink.project_id == project_id, or_(OfferLink.endpoint_id.is_(None), PostbackEndpoint.is_active.is_(False), PostbackEndpoint.is_archived.is_(True)))
    if bot_id:
        planned = planned.where(Bot.id == bot_id)
        issued = issued.where(OfferLink.attribution_json["bot_id"].astext == str(bot_id))
    if link_id: issued = issued.where(OfferLink.attribution_json["tracking_link_id"].astext == str(link_id))
    incomplete = bool(await db.scalar(select(or_(planned.exists(), issued.exists()))))
    return {"incomplete": incomplete, "counts_are_observed_events": True}


@router.post("/qualification/{conversion_id}")
async def qualify(conversion_id: UUID, data: QualificationWrite, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await OfferPayoutService(db).qualify(project_id, actor, conversion_id, data)


async def funnel_version(db, version_id, project_id, actor):
    require_project_access(actor, project_id)
    row = await db.scalar(select(FunnelVersion).join(Funnel, Funnel.id == FunnelVersion.funnel_id).where(
        FunnelVersion.id == version_id, Funnel.project_id == project_id))
    if row is None: raise HTTPException(404)
    return row


@router.get("/funnel-versions/{version_id}")
async def get_funnel_offer(version_id: UUID, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await funnel_version(db, version_id, project_id, actor)
    return {"offer_id": row.offer_id}


@router.put("/funnel-versions/{version_id}")
async def set_funnel_offer(version_id: UUID, data: FunnelOfferWrite, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.funnel_offer_service import get_draft_offer_assignment
    row, _ = await get_draft_offer_assignment(db, project_id, version_id, data.offer_id, actor)
    row.offer_id = data.offer_id
    await db.flush()
    return {"offer_id": row.offer_id}


@router.get("/{offer_id}/settings")
async def offer_settings(offer_id: UUID, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    manage_access(actor, project_id)
    row = await db.get(GamblingOffer, offer_id)
    if not row or row.project_id != project_id: raise HTTPException(404)
    endpoint = await db.get(PostbackEndpoint, row.endpoint_id) if row.endpoint_id else None
    from app.services.postback_endpoint_service import PostbackEndpointService
    return {**GamblingOfferService.public_offer(row), "payout_policy_id": row.payout_policy_id,
        "postback_mapping": endpoint.parameter_mapping if endpoint else None,
        "postback": PostbackEndpointService(db)._endpoint_out(endpoint).model_dump(mode="json") if endpoint else None}


@router.put("/{offer_id}")
async def update(offer_id: UUID, data: OfferWrite, project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await GamblingOfferService(db).save(project_id, actor, data, offer_id)


lead_router = APIRouter(prefix="/leads", tags=["lead-deposits"])


@lead_router.get("/{lead_id}/deposit-summary")
async def deposit_summary(lead_id: UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    project_id: UUID = Depends(get_current_project_id), actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_project_access(actor, project_id)
    from app.core.constants import RoleName
    if actor.role_name == RoleName.BUYER: raise HTTPException(403)
    lead = await db.scalar(select(Lead).where(Lead.id == lead_id, Lead.project_id == project_id, Lead.is_deleted.is_(False)))
    if lead is None: raise HTTPException(404)
    base = [LeadEvent.lead_id == lead_id, LeadEvent.project_id == project_id,
            LeadEvent.event_type.in_(["registration", "deposit", "redeposit"])]
    from app.models.gambling_offer import OfferConversion
    rows = (await db.execute(select(LeadEvent, OfferConversion.event_time_confirmed).outerjoin(
        OfferConversion, OfferConversion.event_id == LeadEvent.id).where(*base).order_by(LeadEvent.occurred_at.desc(), LeadEvent.id.desc())
                            .limit(limit).offset(offset))).all()
    aggregates = (await db.execute(select(LeadEvent.currency, func.sum(LeadEvent.amount),
        func.count().filter(LeadEvent.amount.is_(None))).where(*base, LeadEvent.event_type.in_(["deposit", "redeposit"]))
        .group_by(LeadEvent.currency))).all()
    from app.models.gambling_offer import OfferLink
    modes = set((await db.scalars(select(OfferLink.endpoint_id.is_not(None)).where(OfferLink.lead_id == lead_id))).all())
    return {"events": [{"id": r.id, "event_type": r.event_type, "occurred_at": r.occurred_at,
                       "amount": str(r.amount) if r.amount is not None else None, "currency": r.currency,
                       "time_confirmed": confirmed is not False} for r, confirmed in rows],
        "totals": [{"currency": currency, "amount": str(amount) if amount is not None else None, "unknown_amount_count": unknown}
                   for currency, amount, unknown in aggregates],
        "total_events": await db.scalar(select(func.count()).select_from(LeadEvent).where(*base)),
        "automatic_tracking": True if modes == {True} else False if modes == {False} else None,
        "data_complete": False}
