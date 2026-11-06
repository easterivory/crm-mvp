"""Estimated commission, in its own currency; deposits are never treated as revenue."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import case, func, select

from app.models.gambling_offer import OfferPayoutPolicy, OfferPayoutVersion, OfferConversion
from app.schemas.gambling_offer import PayoutTerms
from app.services.gambling_offer_service import manage_access


def payout_total(count: int, terms: PayoutTerms) -> Decimal:
    rate, total = terms.rate, terms.rate * count
    if terms.tier_mode == "retroactive":
        for tier in terms.tiers:
            if tier.rate is not None and count >= tier.threshold: rate = tier.rate
        total = rate * count
    else:
        # "Above the threshold" means the first threshold FD retain the earlier rate.
        for tier in terms.tiers:
            if tier.rate is not None:
                total += max(0, count - tier.threshold) * (tier.rate - rate)
                rate = tier.rate
    total += sum((tier.bonus for tier in terms.tiers if tier.bonus is not None and count >= tier.threshold), Decimal("0"))
    return total.quantize(Decimal("0.01"))


def period_bounds(day: date, terms: PayoutTerms):
    if terms.period == "custom":
        if not terms.period_from <= day <= terms.period_to: return None
        start, end = terms.period_from, terms.period_to + timedelta(days=1)
    elif terms.period == "month":
        start = day.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif terms.period == "week":
        start = day - timedelta(days=day.weekday()); end = start + timedelta(days=7)
    else:
        start, end = day, day + timedelta(days=1)
    zone = ZoneInfo(terms.timezone)
    return (datetime.combine(start, time.min, zone).astimezone(timezone.utc),
            datetime.combine(end, time.min, zone).astimezone(timezone.utc))


class OfferPayoutService:
    def __init__(self, db): self.db = db

    async def save_policy(self, project_id, actor, data, policy_id=None):
        manage_access(actor, project_id)
        from app.services.gambling_offer_service import GamblingOfferService
        await GamblingOfferService(self.db).project(project_id)
        row = await self.db.get(OfferPayoutPolicy, policy_id, with_for_update=True, populate_existing=True) if policy_id else None
        if policy_id and (not row or row.project_id != project_id): raise HTTPException(404)
        if row and (row.count_scope != data.count_scope or row.partner_name != data.partner_name):
            raise HTTPException(409, "ПП и область подсчёта неизменяемы: создайте отдельные условия")
        if row is None:
            row = OfferPayoutPolicy(id=uuid4(), project_id=project_id, name=data.name,
                partner_name=data.partner_name, count_scope=data.count_scope, current_version=1)
            self.db.add(row); await self.db.flush()
        else:
            row.name = data.name; row.current_version += 1
        version = OfferPayoutVersion(id=uuid4(), policy_id=row.id, version=row.current_version,
            terms_json=data.terms.model_dump(mode="json"), created_at=datetime.now(timezone.utc), created_by_id=actor.id)
        self.db.add(version); await self.db.flush()
        return {"id": row.id, "version": row.current_version}

    async def policies(self, project_id, actor):
        manage_access(actor, project_id)
        rows = (await self.db.execute(select(OfferPayoutPolicy, OfferPayoutVersion).join(OfferPayoutVersion,
            (OfferPayoutVersion.policy_id == OfferPayoutPolicy.id) & (OfferPayoutVersion.version == OfferPayoutPolicy.current_version))
            .where(OfferPayoutPolicy.project_id == project_id).order_by(OfferPayoutPolicy.created_at))).all()
        return [{"id": p.id, "name": p.name, "partner_name": p.partner_name, "count_scope": p.count_scope,
                 "version": v.version, "terms": v.terms_json} for p, v in rows]

    async def report(self, project_id, actor, day: date, policy_id=None):
        manage_access(actor, project_id)
        query = select(OfferPayoutPolicy, OfferPayoutVersion).join(OfferPayoutVersion,
            OfferPayoutVersion.policy_id == OfferPayoutPolicy.id).where(OfferPayoutPolicy.project_id == project_id)
        if policy_id: query = query.where(OfferPayoutPolicy.id == policy_id)
        versions = (await self.db.execute(query.order_by(OfferPayoutPolicy.id, OfferPayoutVersion.version).limit(201))).all()
        if len(versions) > 200: raise HTTPException(422, "Выберите конкретные условия выплаты")
        rows = []
        for policy, version in versions:
            terms = PayoutTerms.model_validate(version.terms_json)
            bounds = period_bounds(day, terms)
            if not bounds: continue
            start, end = bounds
            scope = OfferConversion.offer_id if policy.count_scope == "offer" else None
            # Rank across ALL versions of the same program. Editing a rate must not
            # reset the month's FD counter, and a milestone bonus is earned only once.
            ranked = select(OfferConversion.offer_id.label("offer_id"),
                OfferConversion.payout_version_id.label("version_id"),
                func.row_number().over(partition_by=scope,
                    order_by=(OfferConversion.occurred_at, OfferConversion.id)).label("ordinal"),
                func.count().over(partition_by=scope).label("period_count")).join(OfferPayoutVersion,
                    OfferPayoutVersion.id == OfferConversion.payout_version_id).where(
                    OfferPayoutVersion.policy_id == policy.id, OfferConversion.project_id == project_id,
                    OfferConversion.event_type == "deposit", OfferConversion.qualified.is_(True),
                    OfferConversion.occurred_at >= start, OfferConversion.occurred_at < end).subquery()
            rate = terms.rate
            for tier in terms.tiers:
                if tier.rate is not None:
                    condition = ranked.c.period_count >= tier.threshold if terms.tier_mode == "retroactive" else ranked.c.ordinal > tier.threshold
                    rate = case((condition, tier.rate), else_=rate)
            reward = rate
            for tier in terms.tiers:
                if tier.bonus is not None:
                    reward = reward + case((ranked.c.ordinal == tier.threshold, tier.bonus), else_=Decimal("0"))
            earned_query = select(func.sum(reward)).where(ranked.c.version_id == version.id)
            if scope is not None: earned_query = earned_query.add_columns(ranked.c.offer_id).group_by(ranked.c.offer_id)
            earned = {}
            for earned_row in (await self.db.execute(earned_query)).all():
                earned[earned_row[1] if scope is not None else None] = Decimal(earned_row[0] or 0)
            stmt = select(func.count().filter(OfferConversion.qualified.is_(True)),
                func.count().filter(OfferConversion.qualified.is_(False)),
                func.count().filter(OfferConversion.qualified.is_(None))).where(OfferConversion.project_id == project_id,
                OfferConversion.payout_version_id == version.id, OfferConversion.event_type == "deposit",
                OfferConversion.occurred_at >= start, OfferConversion.occurred_at < end)
            if scope is not None: stmt = stmt.add_columns(scope).group_by(scope)
            for record in (await self.db.execute(stmt)).all():
                qualified, rejected, pending = record[:3]
                if not qualified + rejected + pending: continue
                rows.append({"policy_id": policy.id, "policy_name": policy.name, "version": version.version,
                    "offer_id": record[3] if scope is not None else None, "count_scope": policy.count_scope,
                    "period_from": start, "period_to_exclusive": end, "timezone": terms.timezone,
                    "qualified_fd": qualified, "rejected_fd": rejected, "pending_fd": pending,
                    "currency": terms.currency, "estimated_commission": str(earned.get(record[3] if scope is not None else None,
                        Decimal("0")).quantize(Decimal("0.01")))})
        unpriced = await self.db.scalar(select(func.count()).select_from(OfferConversion).where(
            OfferConversion.project_id == project_id, OfferConversion.event_type == "deposit",
            OfferConversion.payout_version_id.is_(None), OfferConversion.qualified.is_(None)))
        return {"rows": rows, "kind": "estimated_commission", "historical_repricing": False, "unpriced_fd_all_time": unpriced}

    async def pending(self, project_id, actor):
        manage_access(actor, project_id)
        rows = (await self.db.scalars(select(OfferConversion).where(OfferConversion.project_id == project_id,
            OfferConversion.event_type == "deposit",
            OfferConversion.qualified.is_(None)).order_by(OfferConversion.created_at).limit(100))).all()
        return [{"id": r.id, "lead_id": r.lead_id, "offer_id": r.offer_id, "event_id": r.event_id,
                 "reason": r.qualification_reason, "occurred_at": r.occurred_at} for r in rows]

    async def qualify(self, project_id, actor, conversion_id, data):
        manage_access(actor, project_id)
        row = await self.db.scalar(select(OfferConversion).where(OfferConversion.id == conversion_id,
            OfferConversion.project_id == project_id).with_for_update())
        if not row or row.event_type != "deposit": raise HTTPException(404)
        if row.qualified is not None: raise HTTPException(409, "Квалификация уже зафиксирована")
        review = {"previous_occurred_at": row.occurred_at.isoformat(),
            "previous_payout_version_id": str(row.payout_version_id) if row.payout_version_id else None,
            "previous_reason": row.qualification_reason}
        if data.qualified:
            from app.services.gambling_offer_service import GamblingOfferService
            from app.models.lead_event import LeadEvent
            if row.qualification_reason == "fd_time_not_provided" and data.occurred_at is None:
                raise HTTPException(422, "Для выбора условий укажите фактическое время FD")
            actual_time = data.occurred_at or row.occurred_at
            version = await GamblingOfferService(self.db).payout_at(row.offer_id, actual_time)
            if version is None: raise HTTPException(422, "На указанную дату FD не было условий выплаты; ставку не угадываем")
            terms = PayoutTerms.model_validate(version.terms_json)
            if period_bounds(actual_time.astimezone(ZoneInfo(terms.timezone)).date(), terms) is None:
                raise HTTPException(422, "FD вне периода программы")
            row.payout_version_id = version.id
            if data.occurred_at:
                event = await self.db.get(LeadEvent, row.event_id)
                event.occurred_at = actual_time
                row.occurred_at = actual_time
                row.event_time_confirmed = True
        row.review_json = {**review, "occurred_at": row.occurred_at.isoformat(),
            "payout_version_id": str(row.payout_version_id) if row.payout_version_id else None}
        row.qualified, row.qualification_reason = data.qualified, data.reason
        row.reviewed_by_id, row.reviewed_at = actor.id, datetime.now(timezone.utc)
        await self.db.flush()
        return {"id": row.id, "qualified": row.qualified}
