"""Offer configuration and personal URL issuance, without redirects or external HTTP."""
from datetime import datetime, timezone
import hashlib
import secrets
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text

from app.core.constants import RoleName
from app.models import Chat, Lead, Project, TrackingLink
from app.models.funnel import ChatFunnelState, FunnelVersion
from app.models.gambling_offer import GamblingOffer, OfferLink, OfferPayoutPolicy, OfferPayoutVersion, OfferPayoutAssignment, OfferConversion
from app.models.postback import PostbackBinding, PostbackEndpoint
from app.schemas.gambling_offer import OfferWrite
from app.services.access_control import require_project_access
from app.services.postback_contract_service import binding_namespace


def manage_access(actor, project_id):
    require_project_access(actor, project_id)
    if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(403, "Настройки офферов и выплаты доступны администраторам")


def personalize_url(source: str, parameter: str, token: str) -> str:
    parts = urlsplit(source)
    kept = [part for part in parts.query.split("&") if unquote_plus(part.partition("=")[0]) != parameter] if parts.query else []
    kept.append(quote(parameter, safe="") + "=" + quote(token, safe=""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), parts.fragment))


async def advisory(db, key):
    if db.bind.dialect.name == "postgresql":
        number = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


class GamblingOfferService:
    def __init__(self, db): self.db = db

    async def project(self, project_id):
        project = await self.db.get(Project, project_id)
        if not project or project.is_deleted or project.project_format != "gambling":
            raise HTTPException(422, "Офферы доступны в гембл-проектах")
        return project

    async def list_offers(self, project_id, actor):
        require_project_access(actor, project_id)
        await self.project(project_id)
        rows = (await self.db.scalars(select(GamblingOffer).where(GamblingOffer.project_id == project_id)
            .order_by(GamblingOffer.created_at, GamblingOffer.id))).all()
        return [self.public_offer(row) for row in rows]

    @staticmethod
    def public_offer(row):
        # A real allowlist, not ORM serialization followed by hiding fields in React.
        return {key: getattr(row, key) for key in ("id", "project_id", "name", "partner_name", "source_url",
            "postbacks_enabled", "identifier_parameter", "endpoint_id", "is_active")}

    async def save(self, project_id, actor, data: OfferWrite, offer_id=None):
        manage_access(actor, project_id)
        await self.project(project_id)
        row = await self.db.get(GamblingOffer, offer_id, with_for_update=True, populate_existing=True) if offer_id else None
        if offer_id and (not row or row.project_id != project_id): raise HTTPException(404, "Оффер не найден")
        if data.payout_policy_id:
            policy = await self.db.get(OfferPayoutPolicy, data.payout_policy_id)
            if not policy or policy.project_id != project_id or policy.partner_name.casefold() != data.partner_name.casefold():
                raise HTTPException(422, "Выберите условия выплаты той же ПП и проекта")
        if row and row.partner_name.casefold() != data.partner_name.casefold():
            issued = await self.db.scalar(select(OfferLink.id).where(OfferLink.offer_id == row.id).limit(1))
            if issued: raise HTTPException(409, "Для другой ПП создайте новый оффер: уже есть выданные ссылки")
        if row is None:
            row = GamblingOffer(id=uuid4(), project_id=project_id)
            self.db.add(row)
        previous_endpoint_id = row.endpoint_id
        previous_policy_id = row.payout_policy_id
        for key in ("name", "partner_name", "source_url", "postbacks_enabled", "identifier_parameter", "payout_policy_id", "is_active"):
            setattr(row, key, getattr(data, key))
        await self.db.flush()
        if previous_policy_id != row.payout_policy_id:
            self.db.add(OfferPayoutAssignment(id=uuid4(), offer_id=row.id, policy_id=row.payout_policy_id,
                created_at=datetime.now(timezone.utc), created_by_id=actor.id))
        if data.postbacks_enabled:
            mapping = data.postback_mapping.model_copy(update={"identifier_type": "offer_token", "offer_id": row.id,
                "event_namespace": "offer:" + str(row.id), "allowed_event_types": ["registration", "deposit", "redeposit"]})
            old = await self.db.get(PostbackEndpoint, previous_endpoint_id) if previous_endpoint_id else None
            if old is None or old.parameter_mapping != mapping.model_dump(mode="json"):
                # A new parsing contract gets a new endpoint. Old URLs/contracts remain intact.
                from app.schemas.postback import PostbackEndpointCreate
                from app.services.postback_endpoint_service import PostbackEndpointService
                created = await PostbackEndpointService(self.db).create_endpoint(project_id=project_id, actor=actor,
                    data=PostbackEndpointCreate(name=f"Оффер: {row.name}"[:255], event_type="registration",
                        parameter_mapping=mapping, is_active=False))
                row.endpoint_id = created.id
        else:
            row.endpoint_id = None
        await self.db.flush()
        return self.public_offer(row)

    async def template_link(self, chat_id, state):
        if state is None: raise HTTPException(422, "Для {{offer_link}} нужна активная воронка с выбранным оффером")
        version = await self.db.get(FunnelVersion, state.funnel_version_id)
        if version is None or not version.offer_id: raise HTTPException(422, "В настройках версии воронки не выбран оффер")
        lead = await self.db.scalar(select(Lead).where(Lead.chat_id == chat_id, Lead.is_deleted.is_(False)))
        if lead is None: raise HTTPException(422, "Для персональной ссылки нужна карточка лида")
        row = await self.issue(lead, version.offer_id, self.run_key(state), state=state)
        return row.issued_url

    @staticmethod
    def run_key(state):
        return (state.runtime_json or {}).get("offer_run_key") or str(state.id)

    async def issue(self, lead, offer_id, run_key, *, state=None):
        offer = await self.db.get(GamblingOffer, offer_id)
        if not offer or offer.project_id != lead.project_id: raise HTTPException(422, "Оффер не принадлежит проекту лида")
        await self.project(lead.project_id)
        await advisory(self.db, f"offer-link:{lead.id}:{offer_id}:{run_key}")
        old = await self.db.scalar(select(OfferLink).where(OfferLink.lead_id == lead.id,
            OfferLink.offer_id == offer_id, OfferLink.run_key == run_key))
        if old: return old
        if not offer.is_active: raise HTTPException(422, "Оффер отключён: новая ссылка не выдана")
        if offer.postbacks_enabled:
            endpoint = await self.db.get(PostbackEndpoint, offer.endpoint_id)
            if not endpoint or endpoint.is_archived or not endpoint.is_active:
                raise HTTPException(422, "Сначала настройте и включите приём постбэков оффера")
        chat = await self.db.get(Chat, lead.chat_id)
        source = await self.db.get(TrackingLink, chat.tracking_link_id) if chat.tracking_link_id else None
        token = secrets.token_urlsafe(24)
        row = OfferLink(id=uuid4(), project_id=lead.project_id, offer_id=offer_id, lead_id=lead.id,
            run_key=run_key, token=token, issued_url=personalize_url(offer.source_url, offer.identifier_parameter, token)
                if offer.postbacks_enabled else offer.source_url,
            endpoint_id=offer.endpoint_id if offer.postbacks_enabled else None,
            attribution_json={"tracking_link_id": str(chat.tracking_link_id) if chat.tracking_link_id else None,
                "bot_id": str(chat.bot_id) if chat.bot_id else None,
                "buyer_id": str(source.buyer_id) if source and source.buyer_id else None,
                "funnel_id": str(state.funnel_id) if state else None,
                "funnel_version_id": str(state.funnel_version_id) if state else None,
                "fb_data": (lead.custom_fields or {}).get("fb_data") or {}})
        self.db.add(row); await self.db.flush()
        return row

    async def resolve(self, endpoint, config, mapping, identifier, identifier_source):
        if not mapping.offer_id: return None
        if identifier_source == "player_id":
            binding = await self.db.scalar(select(PostbackBinding).where(PostbackBinding.project_id == endpoint.project_id,
                PostbackBinding.namespace == binding_namespace(endpoint, config), PostbackBinding.identifier_type == "player_id",
                PostbackBinding.external_id == identifier))
            value = (binding.attribution_json or {}).get("offer_link_id") if binding else None
            try: link = await self.db.get(OfferLink, UUID(value)) if value else None
            except ValueError: return None
        else:
            link = await self.db.scalar(select(OfferLink).where(OfferLink.token == identifier,
                OfferLink.endpoint_id == endpoint.id))
        if not link or link.project_id != endpoint.project_id or link.offer_id != mapping.offer_id: return None
        return link

    async def existing_effect(self, link, normalized, *, lock=False):
        if normalized["event_type"] not in {"registration", "deposit"}: return None
        if lock: await advisory(self.db, f"offer-conversion:{link.offer_id}:{link.lead_id}:{normalized['event_type']}")
        return await self.db.scalar(select(OfferConversion).where(OfferConversion.offer_id == link.offer_id,
            OfferConversion.lead_id == link.lead_id, OfferConversion.event_type == normalized["event_type"]))

    async def record_conversion(self, link, event, payload, *, manual=False, event_time_known=True):
        from app.schemas.gambling_offer import PayoutTerms
        from app.services.postback_contract_service import extract
        qualified, reason, version = None, None, None
        if event.event_type == "deposit":
            if not event_time_known and not manual: reason = "fd_time_not_provided"
            else: version = await self.payout_at(link.offer_id, event.occurred_at)
            if not version and not reason: reason = "no_terms_at_fd_time"
        if version:
            terms = PayoutTerms.model_validate(version.terms_json)
            if manual:
                reason = "manual_review_required"
            elif not event_time_known:
                reason = "fd_time_not_provided"
            elif event.amount is None:
                reason = "deposit_amount_missing"
            elif terms.min_deposit > 0 and event.currency != terms.deposit_currency:
                reason = "qualification_currency_mismatch"
            elif event.amount < terms.min_deposit:
                qualified, reason = False, "below_minimum_deposit"
            elif terms.qualification_param and extract(payload, terms.qualification_param) is None:
                reason = "qualification_not_received"
            elif terms.qualification_param:
                value = str(extract(payload, terms.qualification_param)).strip().casefold()
                if value in {v.strip().casefold() for v in terms.qualification_values}:
                    qualified, reason = True, "partner_qualification_confirmed"
                elif value in {v.strip().casefold() for v in terms.qualification_rejected_values}:
                    qualified, reason = False, "partner_qualification_rejected"
                else:
                    reason = "partner_qualification_pending"
            elif terms.conditions_note.strip():
                reason = "additional_conditions_require_review"
            else:
                qualified, reason = True, "deposit_conditions_met"
            if event_time_known:
                from app.services.offer_payout_service import period_bounds
                if terms.period == "custom" and period_bounds(event.occurred_at.astimezone(ZoneInfo(terms.timezone)).date(), terms) is None:
                    qualified, reason = False, "outside_program_period"
        row = OfferConversion(id=uuid4(), project_id=event.project_id, offer_id=link.offer_id, lead_id=event.lead_id,
            offer_link_id=link.id, event_id=event.id, event_type=event.event_type, occurred_at=event.occurred_at,
            payout_version_id=version.id if version else None, qualified=qualified, qualification_reason=reason)
        row.event_time_confirmed = event_time_known
        self.db.add(row); await self.db.flush()
        return row

    async def confirm_pending_qualification(self, event_id, payload, *, dry_run=False):
        from app.schemas.gambling_offer import PayoutTerms
        from app.services.postback_contract_service import extract
        query = select(OfferConversion).where(OfferConversion.event_id == event_id)
        row = await self.db.scalar(query if dry_run else query.with_for_update())
        if (not row or row.event_type != "deposit" or row.qualified is not None or row.reviewed_by_id
                or not row.payout_version_id or row.qualification_reason not in {"partner_qualification_pending", "qualification_not_received"}):
            return False
        version = await self.db.get(OfferPayoutVersion, row.payout_version_id)
        terms = PayoutTerms.model_validate(version.terms_json)
        value = extract(payload, terms.qualification_param)
        if value is None: return False
        value = str(value).strip().casefold()
        if value in {v.strip().casefold() for v in terms.qualification_values}:
            if dry_run: return True
            row.qualified, row.qualification_reason = True, "partner_qualification_confirmed"
        elif value in {v.strip().casefold() for v in terms.qualification_rejected_values}:
            if dry_run: return True
            row.qualified, row.qualification_reason = False, "partner_qualification_rejected"
        else: return False
        await self.db.flush()
        return True

    async def payout_at(self, offer_id, occurred_at):
        # Configuration writes hold exclusive locks on these two rows. Independent
        # callbacks share read locks and select history only after a pending edit commits.
        await self.db.execute(select(GamblingOffer.id).where(GamblingOffer.id == offer_id).with_for_update(read=True))
        assignment = await self.db.scalar(select(OfferPayoutAssignment).where(OfferPayoutAssignment.offer_id == offer_id,
            OfferPayoutAssignment.created_at <= occurred_at).order_by(OfferPayoutAssignment.created_at.desc(), OfferPayoutAssignment.id.desc()).limit(1))
        if assignment and assignment.policy_id:
            await self.db.execute(select(OfferPayoutPolicy.id).where(OfferPayoutPolicy.id == assignment.policy_id).with_for_update(read=True))
            return await self.db.scalar(select(OfferPayoutVersion).where(OfferPayoutVersion.policy_id == assignment.policy_id,
                OfferPayoutVersion.created_at <= occurred_at).order_by(OfferPayoutVersion.created_at.desc(), OfferPayoutVersion.version.desc()).limit(1))
        return None

    async def manual_event(self, project_id, actor, lead_id, data):
        from app.models.lead_event import LeadEvent
        from app.services.lead_event_service import LeadEventService
        require_project_access(actor, project_id)
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN, RoleName.MANAGER, RoleName.OPERATOR}:
            raise HTTPException(403)
        kind = LeadEventService.normalize_event_type(data.event_type)
        if kind not in {"registration", "deposit", "redeposit"}: raise HTTPException(422, "Выберите REG / FD / RD")
        lead = await self.db.scalar(select(Lead).where(Lead.id == lead_id, Lead.project_id == project_id,
            Lead.is_deleted.is_(False), Lead.is_trash.is_(False)))
        if lead is None: raise HTTPException(404)
        state = await self.db.scalar(select(ChatFunnelState).where(ChatFunnelState.chat_id == lead.chat_id))
        chat = await self.db.get(Chat, lead.chat_id)
        run_key = self.run_key(state) if state else "manual:" + (chat.current_cycle_started_at or lead.created_at).isoformat()
        link = await self.issue(lead, data.offer_id, run_key, state=state)
        prior = await self.existing_effect(link, {"event_type": kind}, lock=True)
        if prior:
            previous = await self.db.get(LeadEvent, prior.event_id)
            if previous.amount != data.amount or previous.currency != data.currency:
                raise HTTPException(409, "Первое событие уже записано с другими данными")
            return previous
        event, created = await LeadEventService(self.db).record_event(lead=lead, event_type=kind, source="manual",
            amount=data.amount, currency=data.currency, created_by_user_id=actor.id,
            external_event_id=data.external_event_id, payload=data.payload, attribution=link.attribution_json,
            occurred_at=data.occurred_at)
        if created: await self.record_conversion(link, event, data.payload, manual=True)
        return event
