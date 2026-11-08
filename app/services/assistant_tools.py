"""Bounded, allowlisted read tools. No administrative DTO is passed to the cloud."""
import base64
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import func, select, tuple_

from app.core.assistant import cached_report, connection_policy, digest, fail, now, safe_url
from app.models import Bot, Chat, Lead, LeadStatus, Project, TrackingLink
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelEdge
from app.models.gambling_offer import GamblingOffer, OfferConversion
from app.models.lead import LeadTag
from app.models.tag import Tag
from app.models.lead_event import LeadEvent
from app.models.postback import PostbackEndpoint, PostbackReceipt, PostbackRelayHealth
from app.schemas import assistant as schemas
from app.services.assistant_changes import AssistantChanges, fingerprint

TOOLS = {
    "crm_get_access": ("crm.catalog.read", schemas.StrictModel),
    "crm_list_objects": ("crm.catalog.read", schemas.ListQuery),
    "crm_get_configuration": ("crm.configuration.read", schemas.ObjectQuery),
    "crm_get_tracking": ("crm.analytics.read", schemas.TrackingQuery),
    "crm_get_postback_diagnostics": ("crm.diagnostics.read", schemas.DiagnosticsQuery),
    "crm_get_lead_summary": ("crm.leads.summary.read", schemas.LeadQuery),
    "crm_preview_postback": ("crm.configuration.read", schemas.PreviewQuery),
    "crm_prepare_change": ("crm.changes.prepare", schemas.PrepareIn),
    "crm_get_change": ("crm.changes.prepare", schemas.ChangeQuery),
}


def safe_text(value):
    text = str(value or "")[:500]
    if re.search(r"https?://|Bearer\s|[A-Za-z0-9_\-]{24,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text, re.I): return "[redacted]"
    return text


def safe_mapping(value):
    keys = {"identifier_type", "identifier_param", "amount_param", "currency_param", "event_type_param",
        "external_event_id_param", "occurred_at_param", "time_format", "require_event_id", "event_aliases",
        "allowed_event_types", "bind_external_id_param", "bind_external_type"}
    def clean(item):
        if isinstance(item, str): return safe_text(item)
        if isinstance(item, list): return [clean(v) for v in item]
        if isinstance(item, dict): return {safe_text(k): clean(v) for k, v in item.items()}
        return item
    return {k: clean(v) for k, v in value.items() if k in keys}


def catalog_item(kind, row):
    result = {"id": str(row.id)}
    if kind == "bots": result.update(name=safe_text(row.name), username=safe_text(row.bot_username), active_version_id=str(row.active_funnel_version_id) if row.active_funnel_version_id else None)
    elif kind == "tracking_links": result.update(name=safe_text(row.title), bot_id=str(row.bot_id), destination_type=row.destination_type)
    elif kind == "funnel_versions": result.update(funnel_id=str(row.funnel_id), version_number=row.version_number, status=row.status, offer_id=str(row.offer_id) if row.offer_id else None)
    elif kind == "offers": result.update(name=safe_text(row.name), partner_name=safe_text(row.partner_name), url=safe_url(row.source_url), postbacks_enabled=row.postbacks_enabled,
        identifier_parameter=safe_text(row.identifier_parameter), is_active=row.is_active, endpoint_id=str(row.endpoint_id) if row.endpoint_id else None)
    else: result.update(name=safe_text(row.name), processing_kind=row.processing_kind, event_type=row.event_type, is_active=row.is_active,
        is_archived=row.is_archived, revision=row.revision, mapping=safe_mapping(row.parameter_mapping))
    return result


def paginate(query, model, cursor, limit):
    if cursor:
        try:
            stamp, identifier = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None: raise ValueError()
            query = query.where(tuple_(model.created_at, model.id) < tuple_(parsed, UUID(identifier)))
        except Exception: fail("invalid_cursor", 422)
    return query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)


def next_cursor(rows, limit):
    if len(rows) <= limit: return None
    last = rows[limit - 1]
    return base64.urlsafe_b64encode(json.dumps([last.created_at.isoformat(), str(last.id)]).encode()).decode().rstrip("=")


class AssistantTools:
    def __init__(self, db, actor, connection, scopes):
        self.db, self.actor, self.connection, self.scopes = db, actor, connection, scopes

    async def call(self, name, arguments):
        if name not in TOOLS: fail("unsupported_tool", 422)
        scope, model = TOOLS[name]
        if scope not in self.scopes: fail("scope_not_granted")
        try: data = model.model_validate(arguments)
        except ValidationError: fail("invalid_arguments", 422)
        project_id = getattr(data, "project_id", None)
        connection_policy(self.actor, self.connection, scope, project_id)
        if project_id:
            project = await self.db.get(Project, project_id)
            if not project or project.is_deleted or project.status != "active": fail("project_unavailable", 404)
        result = await getattr(self, name)(data)
        envelope = jsonable_encoder({"schema_version": 1, "request_id": uuid4().hex, "project_id": project_id,
            "observed_at": now(), "data": result, "warnings": []})
        def clean(value, key=""):
            # DTO field names are server-owned. Only alias-map keys are user data;
            # redacting long protocol field names would corrupt the contract.
            if isinstance(value, dict): return {safe_text(k) if key == "event_aliases" else k: clean(v, k) for k, v in value.items()}
            if isinstance(value, list): return [clean(v, key) for v in value]
            if key == "identity_resolution" and value in {"not_performed_without_saved_endpoint", "not_performed_for_disabled_endpoint"}: return value
            if isinstance(value, str) and key not in {"id", "request_id", "plan_hash", "next_cursor", "approval_url"} and not key.endswith("_id"):
                return safe_text(value)
            return value
        envelope = clean(envelope)
        if len(json.dumps(envelope).encode()) > 65536: fail("response_too_large", 422)
        return envelope

    async def crm_get_access(self, _):
        from app.core.assistant import project_policy
        projects = []
        for value in self.connection.project_ids:
            try: project_policy(self.actor, value, self.connection)
            except Exception: continue
            row = await self.db.get(Project, UUID(value))
            if row and not row.is_deleted and row.status == "active": projects.append({"id": value, "name": safe_text(row.name), "project_format": row.project_format})
        return {"user_id": str(self.actor.id), "connection_id": str(self.connection.id), "scopes": sorted(self.scopes),
            "projects": projects, "tools": [k for k, (scope, _) in TOOLS.items() if scope in self.scopes]}

    async def crm_list_objects(self, data):
        model = {"bots": Bot, "tracking_links": TrackingLink, "funnel_versions": FunnelVersion,
            "offers": GamblingOffer, "postback_endpoints": PostbackEndpoint}[data.kind]
        query = select(model)
        if model == FunnelVersion: query = query.join(Funnel, Funnel.id == model.funnel_id).where(Funnel.project_id == data.project_id)
        else: query = query.where(model.project_id == data.project_id)
        if hasattr(model, "is_deleted"): query = query.where(model.is_deleted.is_(False))
        rows = (await self.db.scalars(paginate(query, model, data.cursor, data.limit))).all()
        return {"items": [catalog_item(data.kind, row) for row in rows[:data.limit]], "next_cursor": next_cursor(rows, data.limit)}

    async def crm_get_configuration(self, data):
        kind = {"bot": "bots", "offer": "offers", "postback_endpoint": "postback_endpoints", "funnel_version": "funnel_versions"}[data.kind]
        model = {"bot": Bot, "offer": GamblingOffer, "postback_endpoint": PostbackEndpoint, "funnel_version": FunnelVersion}[data.kind]
        row = await self.db.get(model, data.object_id)
        owner = await self.db.get(Funnel, row.funnel_id) if row and model == FunnelVersion else row
        if not row or owner.project_id != data.project_id or getattr(row, "is_deleted", False): fail("not_found", 404)
        result = catalog_item(kind, row)
        if model == FunnelVersion:
            steps = (await self.db.scalars(select(FunnelStep).where(FunnelStep.funnel_version_id == row.id).order_by(FunnelStep.created_at, FunnelStep.id).limit(101))).all()
            if len(steps) > 100: fail("query_too_large", 422)
            edges = (await self.db.scalars(select(FunnelEdge).where(FunnelEdge.funnel_version_id == row.id).limit(501))).all()
            if len(edges) > 500: fail("query_too_large", 422)
            # Do not serialize config_json: it can contain private partner URLs.
            result.update(steps=[{"id": str(s.id), "title": safe_text(s.title), "block_type": s.block_type} for s in steps],
                edges=[{"from_id": str(e.from_step_id), "to_id": str(e.to_step_id)} for e in edges])
        return result

    async def crm_get_tracking(self, data):
        end = data.date_to or now().date()
        start = data.date_from or end - timedelta(days=6)
        if not 0 <= (end - start).days < 366: fail("query_too_large", 422)
        from app.services.tracking_metrics_service import TrackingMetricsService
        service = TrackingMetricsService(self.db)
        if data.bot_id:
            bot = await self.db.get(Bot, data.bot_id)
            if not bot or bot.project_id != data.project_id or bot.is_deleted: fail("not_found", 404)
        if data.link_id:
            link = await self.db.get(TrackingLink, data.link_id)
            if not link or link.project_id != data.project_id or data.bot_id and link.bot_id != data.bot_id: fail("not_found", 404)
        project = await self.db.get(Project, data.project_id)
        cache_key = digest({"schema": 1, "actor": str(self.actor.id), "connection": str(self.connection.id),
            "policy": self.connection.policy_version, "scopes": sorted(self.scopes), "project": fingerprint(project),
            "query": data.model_dump(mode="json"), "start": start.isoformat(), "end": end.isoformat()})
        cached = await cached_report(cache_key)
        if cached is not None:
            return {**cached, "cached": True}
        if data.link_id:
            result = await service.get_link_metrics(current_user=self.actor, link_id=data.link_id,
                date_from=start, date_to=end)
        else:
            result = await service.get_project_metrics(current_user=self.actor, project_id=data.project_id, bot_id=data.bot_id,
                date_from=start, date_to=end)
        fields = set(data.metric_ids)
        report = {"summary": result.summary.model_dump(include=fields), "daily": [row.model_dump(include=fields | {"date"}) for row in result.daily], "date_from": start, "date_to": end,
            "timezone": "UTC", "data_complete": False, "cached": False, "generated_at": now(),
            "definitions": {"starts": "Project-unique first Telegram starts", "leads": "Target lead cards by project tag/status rules; not unique people",
                "deposits": "Observed postbacks/manual events; zero does not prove complete tracking"}}
        await cached_report(cache_key, jsonable_encoder(report))
        return report

    async def crm_get_postback_diagnostics(self, data):
        if data.endpoint_id:
            row = await self.db.get(PostbackEndpoint, data.endpoint_id)
            if not row or row.project_id != data.project_id: fail("not_found", 404)
        last_day = data.date_to or now().date(); first_day = data.date_from or last_day - timedelta(days=6)
        if not 0 <= (last_day - first_day).days < 366: fail("query_too_large", 422)
        start = datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(last_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        base = [PostbackReceipt.project_id == data.project_id, PostbackReceipt.received_at >= start, PostbackReceipt.received_at < end]
        if data.endpoint_id: base.append(PostbackReceipt.endpoint_id == data.endpoint_id)
        counts = (await self.db.execute(select(PostbackReceipt.status, func.count()).where(*base).group_by(PostbackReceipt.status))).all()
        rows = (await self.db.scalars(paginate(select(PostbackReceipt).where(*base), PostbackReceipt, data.cursor, data.limit))).all()
        health = await self.db.scalar(select(PostbackRelayHealth).order_by(PostbackRelayHealth.seen_at.desc()).limit(1))
        return {"counts": dict(counts), "period_start": start, "period_end": end,
            "heartbeat_seen_at": health.seen_at if health else None, "business_delivery_verified": False,
            "items": [{"id": str(r.id), "endpoint_id": str(r.endpoint_id), "status": r.status, "received_at": r.received_at,
                "has_error": bool(r.error_message)} for r in rows[:data.limit]], "next_cursor": next_cursor(rows, data.limit)}

    async def crm_get_lead_summary(self, data):
        row = await self.db.get(Lead, data.lead_id)
        if not row or row.project_id != data.project_id or row.is_deleted: fail("not_found", 404)
        chat = await self.db.get(Chat, row.chat_id)
        tags = (await self.db.scalars(select(Tag.name).join(LeadTag, LeadTag.tag_id == Tag.id).where(LeadTag.lead_id == row.id).limit(100))).all()
        events = (await self.db.scalars(select(LeadEvent).where(LeadEvent.project_id == data.project_id,
            LeadEvent.lead_id == row.id, LeadEvent.event_type.in_(["registration", "deposit", "redeposit"]))
            .order_by(LeadEvent.occurred_at.desc()).limit(50))).all()
        return {"id": str(row.id), "bot_id": str(chat.bot_id), "tracking_link_id": str(chat.tracking_link_id) if chat.tracking_link_id else None,
            "status_id": str(row.status_id), "tags": [safe_text(t) for t in tags],
            "events": [{"event_type": e.event_type, "occurred_at": e.occurred_at, "amount": str(e.amount) if e.amount is not None else None, "currency": e.currency} for e in events], "data_complete": False,
            "events_limit": 50, "may_be_truncated": len(events) == 50}

    async def crm_preview_postback(self, data):
        if len(json.dumps(data.sample).encode()) > 16384: fail("sample_too_large", 422)
        if data.draft_contract is not None:
            from app.services.postback_contract_service import normalize
            try:
                normalize({"processing_kind": "lifecycle_event", "event_type": data.event_type,
                    "parameter_mapping": data.draft_contract.model_dump(mode="json")}, data.sample, now())
                status = "syntax_valid"
            except (ValueError, ArithmeticError, TypeError): status = "invalid"
            return {"status": status, "identity_resolution": "not_performed_without_saved_endpoint", "dry_run": True, "business_writes": False}
        endpoint = await self.db.get(PostbackEndpoint, data.endpoint_id)
        if not endpoint or endpoint.project_id != data.project_id: fail("not_found", 404)
        from app.services.postback_contract_service import PostbackContractService, config_of, normalize
        if endpoint.is_archived: fail("not_found", 404)
        if not endpoint.is_active:
            try:
                normalize(config_of(endpoint), data.sample, now())
                status = "syntax_valid"
            except (ValueError, ArithmeticError, TypeError): status = "invalid"
            return {"status": status, "identity_resolution": "not_performed_for_disabled_endpoint", "dry_run": True, "business_writes": False}
        result = await PostbackContractService(self.db).receive(token=endpoint.secret_token, method="POST", query={}, body=data.sample, dry_run=True)
        return {"status": result["status"], "dry_run": True, "business_writes": False}

    async def crm_prepare_change(self, data): return await AssistantChanges(self.db).prepare(self.actor, self.connection, data)

    async def crm_get_change(self, data):
        service = AssistantChanges(self.db)
        row = await service.owned(self.actor, data.proposal_id, self.connection)
        if row.project_id != data.project_id: fail("not_found", 404)
        return service.public(row)
