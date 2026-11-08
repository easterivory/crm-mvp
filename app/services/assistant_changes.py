"""Prepare immutable plans; only the CRM user endpoint may atomically apply them."""
import json
from datetime import timedelta
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import exists, select
from fastapi import HTTPException

from app.core.assistant import connection_policy, digest, enabled, fail, now, project_policy, safe_url
from app.core.config import settings
from app.models import Project
from app.models.assistant import AssistantConnection, AssistantProposal, AssistantSecureInput
from app.models.gambling_offer import GamblingOffer, OfferLink
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion
from app.models.postback import PostbackEndpoint, PostbackEndpointRevision, PostbackReceipt
from app.schemas.assistant import PrepareIn
from app.schemas.gambling_offer import OfferWrite
from app.schemas.postback import PostbackEndpointCreate, PostbackEndpointUpdate
from app.services.audit_service import AuditService
from app.services.gambling_offer_service import GamblingOfferService, advisory
from app.services.postback_endpoint_service import PostbackEndpointService

HANDLER_VERSION = 1


def cipher():
    try: return Fernet(settings.ASSISTANT_INPUT_KEY.encode())
    except (ValueError, TypeError): fail("secure_input_key_not_configured", 503)


async def put_input(db, actor, data):
    enabled(changes=True)
    project_policy(actor, data.project_id)
    # Validation does not fetch this URL or create an offer.
    OfferWrite(name="validation", partner_name="validation", source_url=data.value)
    row = AssistantSecureInput(id=uuid4(), user_id=actor.id, project_id=data.project_id,
        kind="source_url", encrypted_value=cipher().encrypt(data.value.encode()), expires_at=now() + timedelta(hours=24))
    db.add(row)
    await db.flush()
    return {"id": str(row.id), "kind": row.kind, "expires_at": row.expires_at, "url": safe_url(data.value)}


async def input_value(db, ref, actor, project_id, permitted_proposals=()):
    row = await db.scalar(select(AssistantSecureInput).where(AssistantSecureInput.id == ref).with_for_update())
    if row is None or row.user_id != actor.id or row.project_id != project_id or row.expires_at <= now(): fail("invalid_secure_input", 422)
    if row.bound_proposal_id and row.bound_proposal_id not in permitted_proposals: fail("secure_input_already_bound", 409)
    try: value = cipher().decrypt(row.encrypted_value).decode()
    except (InvalidToken, UnicodeError): fail("secure_input_unavailable", 503)
    return row, value


def fingerprint(row):
    # Hash private state, but never store or expose secret material in a diff.
    return digest({c.name: str(getattr(row, c.name)) for c in row.__table__.columns})


def mapping_ok(mapping, standalone=False):
    if mapping is None: return
    if mapping.offer_id or mapping.event_namespace or mapping.status_mapping or mapping.status_transitions:
        fail("mapping_field_not_allowed", 422)
    if standalone and mapping.identifier_type in {"offer_token", "tracking_code", "submission_id"}:
        fail("mapping_identifier_not_allowed", 422)
    from app.services.lead_event_service import LeadEventService
    allowed = {"registration", "deposit", "redeposit"}
    if set(mapping.allowed_event_types) - allowed or any(LeadEventService.normalize_event_type(v) not in allowed for v in mapping.event_aliases.values()):
        fail("unsupported_event_type", 422)
    if not standalone and mapping.allowed_event_types and set(mapping.allowed_event_types) != allowed:
        fail("offer_requires_reg_fd_rd", 422)


class AssistantChanges:
    def __init__(self, db): self.db = db

    async def inspect(self, actor, project_id, operations, permitted=()):
        db = self.db
        project_policy(actor, project_id)
        project = await db.get(Project, project_id)
        if not project or project.is_deleted or project.status != "active": fail("project_unavailable", 422)
        snapshots, effects, objects, refs = {"project": fingerprint(project)}, [], [], []
        seen = set()
        for index, operation in enumerate(operations):
            op = operation.model_dump(mode="json", exclude_unset=True)
            kind = operation.kind
            row = None
            target_id = op.get("offer_id") if kind == "offer.update_inactive" else op.get("endpoint_id") if kind == "postback.update_disabled" else op.get("version_id")
            if target_id:
                if target_id in seen: fail("duplicate_plan_target", 422)
                seen.add(target_id)
            if kind.startswith("offer."):
                if project.project_format != "gambling": fail("gambling_project_required", 422)
                if kind == "offer.update_inactive":
                    row = await db.scalar(select(GamblingOffer).where(GamblingOffer.id == operation.offer_id,
                        GamblingOffer.project_id == project_id).with_for_update())
                    if row is None: fail("not_found", 404)
                    used = await db.scalar(select(exists().where(OfferLink.offer_id == row.id)))
                    versions = await db.scalar(select(exists().where(FunnelVersion.offer_id == row.id)))
                    if row.is_active or used or versions: fail("offer_in_use", 409)
                    values = {key: getattr(row, key) for key in ("name", "partner_name", "source_url", "postbacks_enabled", "identifier_parameter", "payout_policy_id")}
                    endpoint = await db.get(PostbackEndpoint, row.endpoint_id) if row.endpoint_id else None
                    revision = await db.get(PostbackEndpointRevision, (endpoint.id, endpoint.revision)) if endpoint else None
                    if endpoint and (endpoint.is_active or endpoint.ever_active or not revision or revision.config_json.get("activity_history_version") != 1): fail("offer_in_use", 409)
                    values["postback_mapping"] = endpoint.parameter_mapping if endpoint else None
                    if endpoint: snapshots["endpoint:" + str(endpoint.id)] = fingerprint(endpoint)
                else:
                    values = {"name": operation.name, "partner_name": operation.partner_name,
                        "postbacks_enabled": operation.postbacks_enabled, "identifier_parameter": operation.identifier_parameter,
                        "postback_mapping": operation.postback_mapping}
                for key in ("name", "partner_name", "postbacks_enabled", "identifier_parameter", "postback_mapping"):
                    if key in op:
                        value = getattr(operation, key)
                        if value is None and key in {"name", "partner_name", "postbacks_enabled"}: fail("invalid_null", 422)
                        values[key] = value
                mapping_ok(operation.postback_mapping)
                if operation.source_url_ref:
                    ref, value = await input_value(db, operation.source_url_ref, actor, project_id, permitted)
                    refs.append(ref); values["source_url"] = value
                    snapshots["input:" + str(ref.id)] = digest(value)
                data = OfferWrite(**values, is_active=False)
                if data.postback_mapping:
                    data.postback_mapping = data.postback_mapping.model_copy(update={"allowed_event_types": ["registration", "deposit", "redeposit"]})
                # Inherited generated offer fields are owned by the business service.
                before = None if row is None else {"name": row.name, "partner_name": row.partner_name,
                    "url": safe_url(row.source_url), "postbacks_enabled": row.postbacks_enabled, "is_active": False}
                after = {"name": data.name, "partner_name": data.partner_name, "url": safe_url(data.source_url),
                    "postbacks_enabled": data.postbacks_enabled, "identifier_parameter": data.identifier_parameter,
                    "postback_mapping": data.postback_mapping.model_dump(mode="json") if data.postback_mapping else None, "is_active": False}
                if operation.source_url_ref: after["secure_input_ref"] = str(operation.source_url_ref)
                # Never disclose a hidden payout assignment through the plan.
                if after["postback_mapping"]:
                    after["postback_mapping"].pop("offer_id", None)
                    after["postback_mapping"].pop("event_namespace", None)
                effect = {"kind": kind, "target_id": str(row.id) if row else None, "before": before, "after": after,
                    "consequences": ["Offer remains disabled", "New parsing contract creates a disabled endpoint; existing endpoints are not changed"]}
                objects.append((kind, row, data))
            elif kind.startswith("postback."):
                if kind == "postback.update_disabled":
                    row = await db.scalar(select(PostbackEndpoint).where(PostbackEndpoint.id == operation.endpoint_id,
                        PostbackEndpoint.project_id == project_id).with_for_update())
                    if row is None: fail("not_found", 404)
                    used = await db.scalar(select(exists().where(PostbackReceipt.endpoint_id == row.id)))
                    revision = await db.get(PostbackEndpointRevision, (row.id, row.revision))
                    known_history = revision and revision.config_json.get("activity_history_version") == 1
                    if row.is_active or row.is_archived or used or row.ever_active or not known_history or row.partner_integration_id or row.processing_kind != "lifecycle_event" or row.parameter_mapping.get("offer_id"):
                        fail("endpoint_in_use_or_not_standalone", 409)
                    values = {"name": row.name, "event_type": row.event_type, "parameter_mapping": row.parameter_mapping}
                    for key in values:
                        if key in op:
                            if getattr(operation, key) is None: fail("invalid_null", 422)
                            values[key] = getattr(operation, key)
                else:
                    values = {"name": operation.name, "event_type": operation.event_type, "parameter_mapping": operation.parameter_mapping}
                data = PostbackEndpointCreate(**values, is_active=False)
                mapping_ok(data.parameter_mapping, standalone=True)
                if not data.parameter_mapping.allowed_event_types:
                    data.parameter_mapping = data.parameter_mapping.model_copy(update={"allowed_event_types": ["registration", "deposit", "redeposit"]})
                objects.append((kind, row, data))
                effect = {"kind": kind, "target_id": str(row.id) if row else None,
                    "before": {"name": row.name, "event_type": row.event_type, "parameter_mapping": row.parameter_mapping, "is_active": False} if row else None,
                    "after": {"name": data.name, "event_type": data.event_type, "parameter_mapping": data.parameter_mapping.model_dump(mode="json"), "is_active": False},
                    "consequences": ["Public intake is not enabled"]}
            else:
                from app.services.funnel_offer_service import get_draft_offer_assignment
                row, offer = await get_draft_offer_assignment(db, project_id, operation.version_id, operation.offer_id, actor)
                snapshots["offer:" + str(offer.id)] = fingerprint(offer)
                if offer.endpoint_id:
                    endpoint = await db.get(PostbackEndpoint, offer.endpoint_id)
                    if endpoint: snapshots["endpoint:" + str(endpoint.id)] = fingerprint(endpoint)
                objects.append((kind, row, operation.offer_id))
                effect = {"kind": kind, "target_id": str(row.id), "before": {"offer_id": str(row.offer_id) if row.offer_id else None},
                    "after": {"offer_id": str(offer.id), "offer_name": offer.name}, "consequences": ["Draft only; no publication or live funnel changes"]}
            if row is not None: snapshots["target:" + str(row.id)] = fingerprint(row)
            effects.append(effect)
        return snapshots, effects, objects, refs

    async def prepare(self, actor, connection, data: PrepareIn):
        enabled(changes=True)
        connection_policy(actor, connection, "crm.changes.prepare", data.project_id)
        body = data.model_dump(mode="json")
        request_hash = digest(body)
        await advisory(self.db, f"assistant-request:{connection.id}:{data.request_id}")
        old = await self.db.scalar(select(AssistantProposal).where(AssistantProposal.connection_id == connection.id,
            AssistantProposal.request_id == data.request_id))
        if old:
            if old.request_hash != request_hash: fail("request_id_conflict", 409)
            return self.public(old)
        replacement = None
        if data.supersedes_proposal_id:
            replacement = await self.owned(actor, data.supersedes_proposal_id, connection, lock=True)
            if replacement.project_id != data.project_id or replacement.status not in {"draft", "pending_approval"}: fail("cannot_replace_proposal", 409)
        # Deterministic order prevents competing multi-object plans reversing locks.
        targets = [op.model_dump(mode="json").get("offer_id") or op.model_dump(mode="json").get("endpoint_id") or op.model_dump(mode="json").get("version_id") or "" for op in data.operations]
        if len([x for x in targets if x]) != len(set(x for x in targets if x)): fail("duplicate_plan_target", 422)
        operations = sorted(data.operations, key=lambda op: json.dumps(op.model_dump(mode="json"), sort_keys=True))
        snapshots, effects, _, refs = await self.inspect(actor, data.project_id, operations, (replacement.id,) if replacement else ())
        plan = {"operations": [op.model_dump(mode="json", exclude_unset=True) for op in operations], "effects": effects}
        row = AssistantProposal(id=uuid4(), user_id=actor.id, connection_id=connection.id, project_id=data.project_id,
            request_id=data.request_id, request_hash=request_hash, handler_version=HANDLER_VERSION,
            status="pending_approval", plan_json=plan, snapshot_json=snapshots,
            plan_hash=digest({"plan": plan, "snapshot": snapshots, "handler": HANDLER_VERSION}), expires_at=now() + timedelta(minutes=30))
        self.db.add(row); await self.db.flush()
        for ref in refs: ref.bound_proposal_id = row.id
        if replacement: replacement.status = "cancelled"
        await self.audit(row, actor, "assistant.prepare")
        return self.public(row)

    async def owned(self, actor, proposal_id, connection=None, lock=False):
        query = select(AssistantProposal).where(AssistantProposal.id == proposal_id, AssistantProposal.user_id == actor.id)
        row = await self.db.scalar(query.with_for_update() if lock else query)
        if row is None: fail("not_found", 404)
        query = select(AssistantConnection).where(AssistantConnection.id == row.connection_id)
        conn = await self.db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
        if connection and conn.id != connection.id: fail("not_found", 404)
        connection_policy(actor, conn, "crm.changes.prepare", row.project_id)
        return row

    async def apply(self, actor, proposal_id, expected_hash):
        enabled(changes=True)
        from app.models import User
        from sqlalchemy.orm import selectinload
        actor = await self.db.scalar(select(User).where(User.id == actor.id).options(selectinload(User.role), selectinload(User.project_accesses))
            .with_for_update(key_share=True).execution_options(populate_existing=True))
        row = await self.owned(actor, proposal_id, lock=True)
        if row.plan_hash != expected_hash: fail("stale_plan", 409)
        if row.status == "applied": return self.public(row)
        if row.status != "pending_approval": fail("proposal_not_pending", 409)
        if row.expires_at <= now():
            row.status = "expired"
            return self.public(row)
        if row.handler_version != HANDLER_VERSION:
            row.status = "stale"
            return self.public(row)
        operations = PrepareIn(project_id=row.project_id, request_id=row.request_id,
            operations=row.plan_json["operations"]).operations
        try:
            snapshot, effects, objects, _ = await self.inspect(actor, row.project_id, operations, (row.id,))
        except HTTPException as exc:
            if exc.status_code not in {404, 409, 422}: raise
            row.status, row.error_code = "stale", "dependencies_changed"
            return self.public(row)
        if snapshot != row.snapshot_json or effects != row.plan_json["effects"]:
            row.status = "stale"
            return self.public(row)
        results = []
        # A savepoint contains all business changes and their audit. No external I/O.
        try:
            async with self.db.begin_nested():
                for kind, target, data in objects:
                    if kind.startswith("offer."):
                        result = await GamblingOfferService(self.db).save(row.project_id, actor, data, target.id if target else None)
                        results.append({"kind": kind, "id": str(result["id"]), "endpoint_id": str(result["endpoint_id"]) if result["endpoint_id"] else None})
                    elif kind.startswith("postback."):
                        service = PostbackEndpointService(self.db)
                        if target:
                            result = await service.update_endpoint(endpoint_id=target.id, project_id=row.project_id, actor=actor,
                                data=PostbackEndpointUpdate(**data.model_dump()))
                        else: result = await service.create_endpoint(project_id=row.project_id, actor=actor, data=data)
                        results.append({"kind": kind, "id": str(result.id)})
                    else:
                        target.offer_id = data
                        results.append({"kind": kind, "id": str(target.id), "offer_id": str(data)})
                await self.db.flush()
                row.approved_by_id, row.approved_at = actor.id, now()
                row.status, row.result_json = "applied", {"operations": results}
                await self.audit(row, actor, "assistant.apply")
        except Exception:
            # No exceptions/SQL/partner values are exposed. Rollback to savepoint.
            await self.db.refresh(row)
            row.status, row.error_code = "failed", "atomic_apply_failed"
        return self.public(row)

    async def audit(self, row, actor, action):
        await AuditService(self.db).log(project_id=row.project_id, actor_id=actor.id, action=action,
            entity_type="assistant_proposal", entity_id=row.id,
            meta={"source": "cloud_assistant", "connection_id": str(row.connection_id), "plan_hash": row.plan_hash, "status": row.status})

    @staticmethod
    def public(row):
        status = "expired" if row.status == "pending_approval" and row.expires_at <= now() else row.status
        return {"id": str(row.id), "project_id": str(row.project_id), "status": status,
            "handler_version": row.handler_version, "plan_hash": row.plan_hash, "expires_at": row.expires_at,
            "effects": row.plan_json["effects"], "result": row.result_json, "error_code": row.error_code,
            "approval_url": settings.BASE_URL.rstrip("/") + "/settings?assistant_proposal=" + str(row.id),
            "warnings": ["No activation, publication, messages, test conversions or server changes will be performed"]}
