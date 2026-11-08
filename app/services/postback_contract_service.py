"""Versioned postback contracts. All effects participate in the caller's transaction."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select, text

from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.postback import PostbackBinding, PostbackBusinessEffect, PostbackEndpoint, PostbackEndpointRevision, PostbackReceipt
from app.models.project import Project
from app.models.tracking import TrackingLink
from app.schemas.postback import PostbackParameterMapping, PublicPostbackResult
from app.services.lead_event_service import LeadEventService


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def extract(payload, path):
    value = payload
    for part in (path or "").split("."):
        if not part or not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def amount_value(value):
    if value in (None, ""):
        return None
    amount = Decimal(str(value).strip().replace(" ", "").replace(",", "."))
    if not amount.is_finite() or amount < 0 or amount > Decimal("9999999999999999.99"):
        raise ValueError("Invalid or out-of-range amount")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Amount supports at most two decimal places")
    return amount


def config_of(endpoint):
    return {"event_type": endpoint.event_type, "processing_kind": endpoint.processing_kind,
        "parameter_mapping": endpoint.parameter_mapping or {},
        "partner_integration_id": str(endpoint.partner_integration_id) if endpoint.partner_integration_id else None}


def binding_namespace(endpoint, config=None):
    mapping = config.get("parameter_mapping", {}) if config else (getattr(endpoint, "parameter_mapping", None) or {})
    group = mapping.get("event_namespace")
    if group:
        return "group:" + hashlib.sha256(group.encode()).hexdigest()
    return (config.get("partner_integration_id") if config else str(endpoint.partner_integration_id or "")) or str(endpoint.id)


def business_signature(endpoint, config, mapping, normalized, lead, submission):
    namespace = f"{endpoint.project_id}:{mapping.event_namespace or str(endpoint.id)}"
    fingerprint = hashlib.sha256(json.dumps({"lead": str(lead.id),
        "submission": str(submission.id) if submission and config.get("processing_kind") == "submission_status" else None,
        "event": normalized["event_type"],
        "amount": str(normalized["amount"].normalize()) if normalized["amount"] is not None else None,
        "currency": normalized["currency"],
        "occurred_at": normalized["occurred_at"].isoformat() if mapping.occurred_at_param else None}, sort_keys=True).encode()).hexdigest()
    return namespace, fingerprint


async def status_problem(db, mapping, normalized, submission):
    from app.models.lead_status import LeadStatus
    last = submission.callback_occurred_at
    current = submission.partner_status or ""
    target = normalized["event_type"]
    if last is not None and normalized["occurred_at"] < aware(last):
        return None, "stale", "Older than the applied partner status"
    if last is not None and current != target and current and target not in mapping.status_transitions.get(current, []):
        return None, "conflict", "Status transition is not configured"
    status = await db.scalar(select(LeadStatus).where(LeadStatus.code == mapping.status_mapping[target]))
    return (status, None, None) if status else (None, "invalid", "Mapped CRM status does not exist")


async def snapshot(db, endpoint):
    key = (endpoint.id, endpoint.revision)
    existing = await db.get(PostbackEndpointRevision, key)
    if existing is None:
        await db.execute(select(PostbackEndpoint.id).where(PostbackEndpoint.id == endpoint.id).with_for_update())
        existing = await db.get(PostbackEndpointRevision, key, populate_existing=True)
    if existing is None:
        row = PostbackEndpointRevision(endpoint_id=endpoint.id, revision=endpoint.revision,
            token_hash=hashlib.sha256(endpoint.secret_token.encode()).hexdigest(),
            config_json={**config_of(endpoint), "activity_history_version": 1})
        db.add(row)
        await db.flush()
    return existing


async def remember_personal_link(db, lead_id):
    """Keep attribution of the first per-card link, independently of mutable chat source."""
    from sqlalchemy.dialects.postgresql import insert
    lead = await db.get(Lead, lead_id)
    if lead is None:
        return
    row = (await db.execute(select(Chat.tracking_link_id, Chat.bot_id, TrackingLink.buyer_id, ChatFunnelState.funnel_id, ChatFunnelState.funnel_version_id)
        .select_from(Chat).outerjoin(ChatFunnelState, ChatFunnelState.chat_id == Chat.id)
        .outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(Chat.id == lead.chat_id))).one()
    await db.execute(insert(PostbackBinding).values(id=uuid4(), project_id=lead.project_id, namespace="lead_link",
        identifier_type="lead_id", external_id=str(lead.id), lead_id=lead.id,
        attribution_json={**{key: str(value) if value else None for key, value in row._mapping.items()},
            "fb_data": (lead.custom_fields or {}).get("fb_data") or {}})
        .on_conflict_do_nothing())


def normalize(config, payload, received_at):
    mapping = PostbackParameterMapping.model_validate(config.get("parameter_mapping") or {})
    identifier = extract(payload, mapping.identifier_param)
    identifier_source = "token"
    if mapping.identifier_type == "offer_token" and identifier in (None, "") and mapping.bind_external_type == "player_id":
        identifier = extract(payload, mapping.bind_external_id_param)
        identifier_source = "player_id"
    if identifier is None or isinstance(identifier, (dict, list, bool)) or not str(identifier).strip():
        raise ValueError("Missing or invalid lead/submission identifier")
    raw_type = extract(payload, mapping.event_type_param) if mapping.event_type_param else config["event_type"]
    if raw_type is None or isinstance(raw_type, (dict, list, bool)) or not str(raw_type).strip():
        raise ValueError("Event type/status is missing or invalid")
    event_type = str(raw_type).strip().lower()
    if len(event_type) > 100:
        raise ValueError("Event type/status exceeds 100 characters")
    if config.get("processing_kind") == "submission_status":
        if event_type not in mapping.status_mapping:
            raise ValueError("Partner status is not configured")
    else:
        event_type = mapping.event_aliases.get(event_type, event_type)
        event_type = LeadEventService.normalize_event_type(event_type)
        if mapping.allowed_event_types and event_type not in mapping.allowed_event_types:
            raise ValueError("Unsupported lifecycle event; configure an alias")
    external = extract(payload, mapping.external_event_id_param)
    if external is not None and (isinstance(external, (dict, list, bool)) or not str(external).strip() or len(str(external)) > 255):
        raise ValueError("Invalid external event ID (maximum 255 characters)")
    external = str(external).strip() if external is not None else None
    if (mapping.require_event_id or event_type == "redeposit") and not external:
        raise ValueError("Unique partner event ID is required")
    amount = amount_value(extract(payload, mapping.amount_param))
    currency = extract(payload, mapping.currency_param)
    currency = str(currency).strip().upper() if currency not in (None, "") else None
    if currency and not re.fullmatch(r"[A-Z]{3,10}", currency):
        raise ValueError("Invalid currency")
    timestamp = extract(payload, mapping.occurred_at_param)
    occurred_at = received_at
    if mapping.occurred_at_param:
        if timestamp in (None, ""):
            raise ValueError("Partner event time is required")
        if mapping.time_format == "iso":
            occurred_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if occurred_at.tzinfo is None:
                raise ValueError("Partner time must include timezone")
        else:
            occurred_at = datetime.fromtimestamp(float(timestamp) / (1000 if mapping.time_format == "unix_ms" else 1), timezone.utc)
        occurred_at = aware(occurred_at)
        if occurred_at > received_at + timedelta(minutes=5) or occurred_at.year < 2000:
            raise ValueError("Partner event time outside allowed range")
    normalized = {"identifier": str(identifier).strip(), "event_type": event_type, "external_event_id": external,
        "amount": amount, "currency": currency, "occurred_at": occurred_at,
        "time_source": "partner" if timestamp is not None else "gateway_received"}
    if mapping.identifier_type == "offer_token": normalized["identifier_source"] = identifier_source
    return normalized, mapping


class PostbackContractService:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def same_offer_conversion(previous, event, normalized):
        if event.amount != normalized["amount"] or event.currency != normalized["currency"]:
            return False
        return not (previous.event_time_confirmed and normalized["time_source"] == "partner"
                    and aware(event.occurred_at) != aware(normalized["occurred_at"]))

    async def offer_duplicate_update(self, receipt, endpoint, config, mapping, payload, lead, binding):
        """A duplicate may confirm qualification, but may never rebind a different player."""
        from app.models.gambling_offer import OfferLink
        from app.schemas.postback import PostbackBindingCreate
        from app.services.gambling_offer_service import GamblingOfferService
        link = await self.db.get(OfferLink, UUID(binding.attribution_json["offer_link_id"]))
        value = extract(payload, mapping.bind_external_id_param)
        if value is not None:
            try:
                if isinstance(value, (dict, list, bool)): raise ValueError("Invalid player ID")
                identity = await self.bind(SimpleNamespace(id=endpoint.id, project_id=endpoint.project_id,
                    parameter_mapping=config.get("parameter_mapping") or {}, partner_integration_id=None),
                    PostbackBindingCreate(identifier_type="player_id", external_id=str(value), lead_id=lead.id))
                if not (identity.attribution_json or {}).get("offer_link_id"):
                    identity.attribution_json = {**link.attribution_json, "offer_link_id": str(link.id)}
            except (ValueError, HTTPException):
                receipt.status, receipt.error_message = "conflict", "Player identity conflicts with the original FD"
                return
        if await GamblingOfferService(self.db).confirm_pending_qualification(receipt.lead_event_id, payload):
            receipt.status = "processed"

    async def bind(self, endpoint, data):
        namespace = binding_namespace(endpoint)
        lead = await self.db.scalar(select(Lead).where(Lead.id == data.lead_id, Lead.project_id == endpoint.project_id,
            Lead.is_deleted.is_(False)))
        if lead is None:
            raise HTTPException(422, "Lead does not belong to the endpoint project")
        if data.submission_id:
            submission = await self.db.get(LeadSubmission, data.submission_id)
            if not submission or submission.lead_id != lead.id or submission.partner_integration_id != endpoint.partner_integration_id:
                raise HTTPException(422, "Submission does not belong to this lead/partner")
        if self.db.bind.dialect.name == "postgresql":
            key = int.from_bytes(hashlib.sha256(f"binding:{endpoint.project_id}:{namespace}:{data.identifier_type}:{data.external_id}".encode()).digest()[:8], "big", signed=True)
            await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        existing = await self.db.scalar(select(PostbackBinding).where(PostbackBinding.project_id == endpoint.project_id,
            PostbackBinding.namespace == namespace, PostbackBinding.identifier_type == data.identifier_type,
            PostbackBinding.external_id == data.external_id))
        if existing:
            if existing.lead_id != lead.id or existing.submission_id != data.submission_id:
                raise HTTPException(409, "External ID is already bound to a different lead/submission")
            return existing
        attribution = (await self.db.execute(select(Chat.tracking_link_id, Chat.bot_id, TrackingLink.buyer_id, ChatFunnelState.funnel_id, ChatFunnelState.funnel_version_id)
            .select_from(Chat).outerjoin(ChatFunnelState, ChatFunnelState.chat_id == Chat.id)
            .outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(Chat.id == lead.chat_id))).one()
        row = PostbackBinding(id=uuid4(), project_id=endpoint.project_id, namespace=namespace,
            identifier_type=data.identifier_type, external_id=data.external_id, lead_id=lead.id, submission_id=data.submission_id,
            attribution_json={**{k: str(v) if v else None for k, v in attribution._mapping.items()},
                "fb_data": (lead.custom_fields or {}).get("fb_data") or {}})
        self.db.add(row); await self.db.flush()
        return row

    async def endpoint(self, token, *, endpoint_id=None, revision=None, received_at=None):
        digest = hashlib.sha256(token.encode()).hexdigest()
        if endpoint_id is not None and revision is not None:
            row = await self.db.get(PostbackEndpointRevision, (endpoint_id, revision))
            endpoint = await self.db.get(PostbackEndpoint, endpoint_id)
            if row is None or row.token_hash != digest or row.revoked:
                raise HTTPException(404)
        else:
            endpoint = await self.db.scalar(select(PostbackEndpoint).where(PostbackEndpoint.secret_token == token))
            row = None
            if endpoint is None:
                row = await self.db.scalar(select(PostbackEndpointRevision).where(
                    PostbackEndpointRevision.token_hash == digest, PostbackEndpointRevision.revoked.is_(False), PostbackEndpointRevision.valid_until > now())
                    .order_by(PostbackEndpointRevision.revision.desc()).limit(1))
                endpoint = await self.db.get(PostbackEndpoint, row.endpoint_id) if row else None
        if endpoint is None or not endpoint.is_active or endpoint.is_archived:
            raise HTTPException(404)
        project = await self.db.get(Project, endpoint.project_id)
        if project is None or project.is_deleted or project.status != "active":
            raise HTTPException(404)
        if row is not None and row.valid_until is not None and aware(row.valid_until) < aware(received_at or now()):
            raise HTTPException(404)
        return endpoint, row.config_json if row else config_of(endpoint), row.revision if row else endpoint.revision

    async def match(self, endpoint, config, mapping, identifier, identifier_source=None):
        base = select(Lead).where(Lead.project_id == endpoint.project_id, Lead.is_deleted.is_(False), Lead.is_trash.is_(False))
        submission = None
        binding = None
        kind = mapping.identifier_type
        namespace = binding_namespace(endpoint, config)
        if kind == "offer_token":
            from app.services.gambling_offer_service import GamblingOfferService
            link = await GamblingOfferService(self.db).resolve(endpoint, config, mapping, identifier, identifier_source)
            if link is None: return None, None, None, "unmatched"
            base = base.where(Lead.id == link.lead_id)
            binding = SimpleNamespace(attribution_json={**link.attribution_json, "offer_link_id": str(link.id)})
        elif kind in {"click_id", "external_id", "player_id"}:
            binding = await self.db.scalar(select(PostbackBinding).where(PostbackBinding.project_id == endpoint.project_id,
                PostbackBinding.namespace == namespace, PostbackBinding.identifier_type == kind, PostbackBinding.external_id == identifier))
            if binding:
                base = base.where(Lead.id == binding.lead_id)
                if binding.submission_id:
                    submission = await self.db.get(LeadSubmission, binding.submission_id)
            elif kind == "click_id":
                base = base.where(Lead.custom_fields["click_id"].astext == identifier)
            elif kind == "player_id":
                return None, None, None, "unmatched"
            else:
                if not config.get("partner_integration_id"):
                    return None, None, None, "unmatched"
                matches = list((await self.db.scalars(select(LeadSubmission).join(Lead, Lead.id == LeadSubmission.lead_id).where(
                    Lead.project_id == endpoint.project_id, Lead.is_deleted.is_(False), Lead.is_trash.is_(False),
                    LeadSubmission.partner_integration_id == UUID(config["partner_integration_id"]),
                    or_(LeadSubmission.external_id == identifier, LeadSubmission.response_payload["parsed"]["external_id"].astext == identifier)).limit(2))).all())
                if len(matches) != 1:
                    return None, None, None, "ambiguous" if matches else "unmatched"
                submission = matches[0]
                base = base.where(Lead.id == submission.lead_id)
        elif kind in {"lead_id", "chat_id", "submission_id"}:
            try:
                identity = UUID(identifier)
            except ValueError:
                return None, None, None, "unmatched"
            if kind == "submission_id":
                submission = await self.db.get(LeadSubmission, identity)
                if submission is None or str(submission.partner_integration_id) != config.get("partner_integration_id"):
                    return None, None, None, "unmatched"
                base = base.where(Lead.id == submission.lead_id)
            else:
                base = base.where((Lead.id if kind == "lead_id" else Lead.chat_id) == identity)
                if kind == "lead_id":
                    binding = await self.db.scalar(select(PostbackBinding).where(PostbackBinding.project_id == endpoint.project_id,
                        PostbackBinding.namespace == "lead_link", PostbackBinding.identifier_type == "lead_id", PostbackBinding.external_id == str(identity)))
        elif kind == "telegram_id":
            base = base.join(Chat, Chat.id == Lead.chat_id).where(or_(Chat.external_user_id == identifier, Chat.external_chat_id == identifier))
        else:
            # A source link is never a personal identity.
            return None, None, None, "invalid"
        leads = list((await self.db.scalars(base.distinct().limit(2))).all())
        if len(leads) != 1:
            return None, None, binding, "ambiguous" if leads else "unmatched"
        lead = leads[0]
        if config.get("processing_kind") == "submission_status" and submission is None:
            if not config.get("partner_integration_id"):
                return None, None, binding, "invalid"
            submissions = list((await self.db.scalars(select(LeadSubmission).where(LeadSubmission.lead_id == lead.id,
                LeadSubmission.partner_integration_id == UUID(config["partner_integration_id"])).limit(2))).all())
            if len(submissions) != 1:
                return lead, None, binding, "ambiguous" if submissions else "unmatched"
            submission = submissions[0]
        return lead, submission, binding, None

    async def preview_problem(self, endpoint, config, mapping, normalized, lead, submission, payload):
        external = normalized["external_event_id"]
        if external:
            namespace, fingerprint = business_signature(endpoint, config, mapping, normalized, lead, submission)
            existing = await self.db.scalar(select(PostbackBusinessEffect).where(PostbackBusinessEffect.namespace == namespace,
                PostbackBusinessEffect.external_event_id == external))
            if existing:
                return ("duplicate", None) if existing.fingerprint == fingerprint else ("conflict", "Event ID reused with different data")
        if config.get("processing_kind") == "submission_status":
            _, error, reason = await status_problem(self.db, mapping, normalized, submission)
            if error:
                return error, reason
        elif external:
            from app.models.lead_event import LeadEvent
            old = await self.db.scalar(select(LeadEvent).where(LeadEvent.postback_endpoint_id == endpoint.id,
                LeadEvent.external_event_id == external))
            if old:
                same = (old.lead_id == lead.id and old.event_type == normalized["event_type"] and
                    old.amount == normalized["amount"] and old.currency == normalized["currency"])
                return ("duplicate", None) if same else ("conflict", "Existing legacy event has different data")
        if mapping.bind_external_id_param:
            from app.schemas.postback import PostbackBindingCreate
            value = extract(payload, mapping.bind_external_id_param)
            if value is not None:
                try:
                    if isinstance(value, (dict, list, bool)):
                        raise ValueError("External ID must be a scalar identifier")
                    data = PostbackBindingCreate(identifier_type=mapping.bind_external_type, external_id=str(value),
                        lead_id=lead.id, submission_id=submission.id if submission else None)
                except ValueError:
                    return "conflict", "Cannot bind external identity: invalid value"
                existing = await self.db.scalar(select(PostbackBinding).where(PostbackBinding.project_id == endpoint.project_id,
                    PostbackBinding.namespace == binding_namespace(endpoint, config),
                    PostbackBinding.identifier_type == data.identifier_type, PostbackBinding.external_id == data.external_id))
                if existing and (existing.lead_id != data.lead_id or existing.submission_id != data.submission_id):
                    return "conflict", "External ID is already bound to a different lead/submission"
        return None, None

    async def receive(self, *, token, method, query, body, received_at=None, endpoint_id=None, revision=None, dry_run=False, receipt=None):
        received = aware(received_at or now())
        if received > now() + timedelta(minutes=5) or received.year < 2000:
            raise HTTPException(422, "Invalid received_at")
        endpoint, config, revision = await self.endpoint(token, endpoint_id=endpoint_id, revision=revision, received_at=received)
        if not dry_run:
            await snapshot(self.db, endpoint)
        payload = {**query, **body}
        error = None
        normalized = None
        lead = submission = binding = None
        try:
            normalized, mapping = normalize(config, payload, received)
            lead, submission, binding, error = await self.match(endpoint, config, mapping, normalized["identifier"],
                normalized.get("identifier_source"))
        except (ValueError, InvalidOperation, OverflowError, TypeError) as exc:
            error = "invalid"
            reason = str(exc)[:500]
        else:
            reason = {"unmatched": "No exact identity match", "ambiguous": "More than one matching card/submission",
                "invalid": "Unsafe or unsupported identifier mapping"}.get(error)
        if dry_run:
            if not error:
                error, reason = await self.preview_problem(endpoint, config, mapping, normalized, lead, submission, payload)
            if error in {None, "duplicate"} and mapping.identifier_type == "offer_token":
                from app.services.gambling_offer_service import GamblingOfferService
                from app.models.gambling_offer import OfferLink
                from app.models.lead_event import LeadEvent
                player = extract(payload, mapping.bind_external_id_param)
                if player is not None:
                    known = await self.db.scalar(select(PostbackBinding).where(PostbackBinding.project_id == endpoint.project_id,
                        PostbackBinding.namespace == binding_namespace(endpoint, config), PostbackBinding.identifier_type == "player_id",
                        PostbackBinding.external_id == str(player)))
                    if isinstance(player, (dict, list, bool)) or known and known.lead_id != lead.id:
                        return {"status": "conflict", "reason": "Player identity conflicts with the original FD",
                            "lead_id": str(lead.id), "submission_id": None, "revision": revision, "normalized": {}}
                link = await self.db.get(OfferLink, UUID(binding.attribution_json["offer_link_id"]))
                previous = await GamblingOfferService(self.db).existing_effect(link, normalized)
                if previous:
                    old = await self.db.get(LeadEvent, previous.event_id)
                    error = "duplicate" if self.same_offer_conversion(previous, old, normalized) else "conflict"
                    if error == "duplicate" and await GamblingOfferService(self.db).confirm_pending_qualification(old.id, payload, dry_run=True):
                        error, reason = None, "Existing FD; pending qualification will be confirmed without a new deposit"
            return {"status": error or "matched", "reason": reason, "lead_id": str(lead.id) if lead else None,
                "submission_id": str(submission.id) if submission else None, "revision": revision,
                "normalized": {k: str(v) if v is not None else None for k, v in (normalized or {}).items()}}
        if receipt is None:
            receipt = PostbackReceipt(id=uuid4(), endpoint_id=endpoint.id, project_id=endpoint.project_id,
                request_method=method.upper(), query_payload=query, body_payload=body, event_type=str(config["event_type"])[:100], status="unmatched")
            self.db.add(receipt)
        receipt.endpoint_revision = revision
        receipt.received_at = received
        receipt.processed_at = now()
        receipt.lead_id = lead.id if lead else None
        receipt.submission_id = submission.id if submission else None
        receipt.error_message = reason
        if normalized:
            receipt.event_type = normalized["event_type"]
            receipt.occurred_at = normalized["occurred_at"]
        await self.db.flush()
        if error:
            receipt.status = error
            return self.result(receipt)
        external = normalized["external_event_id"]
        namespace, fingerprint = business_signature(endpoint, config, mapping, normalized, lead, submission)
        if external:
            # Namespace lock makes new delivery IDs for the same business event atomic.
            lock = int.from_bytes(hashlib.sha256(f"postback:{namespace}:{external}".encode()).digest()[:8], "big", signed=True)
            if self.db.bind.dialect.name == "postgresql":
                await self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            existing = await self.db.scalar(select(PostbackBusinessEffect).where(PostbackBusinessEffect.namespace == namespace,
                PostbackBusinessEffect.external_event_id == external))
            if existing:
                receipt.status = "duplicate" if existing.fingerprint == fingerprint else "conflict"
                receipt.lead_event_id = UUID(existing.result_json["event_id"]) if existing.result_json.get("event_id") else None
                receipt.error_message = None if receipt.status == "duplicate" else "Event ID reused with different data"
                if receipt.status == "duplicate" and mapping.identifier_type == "offer_token" and receipt.lead_event_id:
                    await self.offer_duplicate_update(receipt, endpoint, config, mapping, payload, lead, binding)
                return self.result(receipt)
        offer_link = None
        if mapping.identifier_type == "offer_token":
            from app.models.gambling_offer import OfferLink
            from app.models.lead_event import LeadEvent
            from app.services.gambling_offer_service import GamblingOfferService
            offer_link = await self.db.get(OfferLink, UUID(binding.attribution_json["offer_link_id"]))
            prior = await GamblingOfferService(self.db).existing_effect(offer_link, normalized, lock=True)
            if prior:
                old = await self.db.get(LeadEvent, prior.event_id)
                receipt.status = "duplicate" if self.same_offer_conversion(prior, old, normalized) else "conflict"
                receipt.lead_event_id = old.id
                receipt.error_message = None if receipt.status == "duplicate" else "First conversion already exists with different amount, currency or time"
                if receipt.status == "duplicate":
                    await self.offer_duplicate_update(receipt, endpoint, config, mapping, payload, lead, binding)
                result = self.result(receipt)
                if external:
                    self.db.add(PostbackBusinessEffect(id=uuid4(), endpoint_id=endpoint.id, external_event_id=external,
                        namespace=namespace, fingerprint=fingerprint, result_json=result.model_dump(mode="json")))
                await self.db.flush()
                return result
        if config.get("processing_kind") == "submission_status":
            # Match the funnel lock order: chat -> lead -> submission.
            await self.db.execute(select(Chat.id).where(Chat.id == lead.chat_id).with_for_update())
            await self.db.refresh(lead, with_for_update=True)
            await self.db.refresh(submission, with_for_update=True)
            current = submission.partner_status or ""
            target = normalized["event_type"]
            status, error, reason = await status_problem(self.db, mapping, normalized, submission)
            if error:
                receipt.status = error; receipt.error_message = reason
                return self.result(receipt)
        elif external:
            from app.models.lead_event import LeadEvent
            old = await self.db.scalar(select(LeadEvent).where(LeadEvent.postback_endpoint_id == endpoint.id,
                LeadEvent.external_event_id == external))
            if old is not None and (old.lead_id != lead.id or old.event_type != normalized["event_type"] or
                    old.amount != normalized["amount"] or old.currency != normalized["currency"]):
                receipt.status = "conflict"; receipt.error_message = "Existing legacy event has different data"
                return self.result(receipt)
        if mapping.bind_external_id_param:
            from app.schemas.postback import PostbackBindingCreate
            value = extract(payload, mapping.bind_external_id_param)
            if value is not None:
                try:
                    if isinstance(value, (dict, list, bool)):
                        raise ValueError("External ID must be a scalar identifier")
                    identity_binding = await self.bind(SimpleNamespace(id=endpoint.id, project_id=endpoint.project_id,
                        parameter_mapping=config.get("parameter_mapping") or {},
                        partner_integration_id=UUID(config["partner_integration_id"]) if config.get("partner_integration_id") else None),
                        PostbackBindingCreate(identifier_type=mapping.bind_external_type, external_id=str(value), lead_id=lead.id,
                            submission_id=submission.id if submission else None))
                    if offer_link is not None and not (identity_binding.attribution_json or {}).get("offer_link_id"):
                        identity_binding.attribution_json = {**offer_link.attribution_json, "offer_link_id": str(offer_link.id)}
                except (ValueError, HTTPException):
                    receipt.status = "conflict"; receipt.error_message = "Cannot bind external identity: conflict or invalid value"
                    return self.result(receipt)
        if config.get("processing_kind") == "submission_status":
            if current != target or lead.status_id != status.id:
                from app.services.postback_service import PostbackService
                helper = PostbackService(self.db)
                from app.repositories.lead_repository import LeadRepository
                from app.models.postback import PostbackFollowup
                old_status_id = lead.status_id
                await LeadRepository(self.db).set_status_by_code(lead.id, lead.project_id, status.code)
                helper._apply_validation_outcome(submission, status.code)
                if old_status_id != status.id:
                    for kind in ("sheets_status", "facebook_status"):
                        self.db.add(PostbackFollowup(id=uuid4(), project_id=lead.project_id, receipt_id=receipt.id,
                            kind=kind, payload_json={"lead_id": str(lead.id), "previous_status_id": str(old_status_id),
                                "current_status_id": str(status.id)}))
                await helper._log_partner_status_event(lead=lead, old_status=current, partner_status=target, payload=payload)
            submission.partner_status = target
            submission.partner_status_updated_at = normalized["occurred_at"]
            submission.callback_occurred_at = normalized["occurred_at"]
        else:
            event_attribution = binding.attribution_json if binding else None
            if event_attribution is None and submission is not None:
                chat = await self.db.get(Chat, lead.chat_id)
                link = await self.db.get(TrackingLink, submission.tracking_link_id) if submission.tracking_link_id else None
                event_attribution = {"tracking_link_id": str(link.id) if link else None,
                    "bot_id": str(chat.bot_id) if chat and chat.bot_id else None,
                    "buyer_id": str(link.buyer_id) if link and link.buyer_id else None,
                    "funnel_id": None, "funnel_version_id": None}
            event, created = await LeadEventService(self.db).record_event(lead=lead, event_type=normalized["event_type"], source="postback",
                amount=normalized["amount"], currency=normalized["currency"], external_event_id=external,
                partner_integration_id=UUID(config["partner_integration_id"]) if config.get("partner_integration_id") else None,
                postback_endpoint_id=endpoint.id, payload=payload, occurred_at=normalized["occurred_at"],
                attribution=event_attribution)
            receipt.lead_event_id = event.id
            if created and offer_link is not None:
                await GamblingOfferService(self.db).record_conversion(offer_link, event, payload,
                    event_time_known=normalized["time_source"] == "partner")
            if created and normalized["event_type"] in {"registration", "deposit", "redeposit"}:
                from app.models.postback import PostbackFollowup
                chat = await self.db.get(Chat, lead.chat_id)
                self.db.add(PostbackFollowup(id=uuid4(), project_id=lead.project_id, receipt_id=receipt.id,
                    kind="facebook_lifecycle", payload_json={"lead_id": str(lead.id), "event_id": str(event.id),
                        "lifecycle_reference": (chat.current_cycle_started_at or lead.created_at).isoformat(),
                        "fb_data": (event_attribution.get("fb_data") or {}) if event_attribution is not None else (lead.custom_fields or {}).get("fb_data") or {}}))
        receipt.status = "duplicate" if config.get("processing_kind") != "submission_status" and not created else "processed"
        result = self.result(receipt)
        if external:
            self.db.add(PostbackBusinessEffect(id=uuid4(), endpoint_id=endpoint.id, external_event_id=external,
                namespace=namespace, fingerprint=fingerprint, result_json=result.model_dump(mode="json")))
        await self.db.flush()
        return result

    @staticmethod
    def result(receipt):
        return PublicPostbackResult(status=receipt.status, receipt_id=receipt.id, lead_id=receipt.lead_id,
            event_id=receipt.lead_event_id, submission_id=receipt.submission_id)
