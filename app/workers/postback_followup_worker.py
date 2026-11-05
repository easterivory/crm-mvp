"""Committed postback side effects. Uncertain external sends require review, not blind resend."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
import time
from sqlalchemy import select, update
from app.core.database import get_db_session
from app.models.postback import PostbackFollowup


async def monitor_postback_transport_task(ctx=None, *, sessions=None):
    from sqlalchemy import func
    from app.core.config import settings
    from app.models.postback import PostbackEndpoint, PostbackRelayHealth
    from app.models.project import Project
    from app.services.postback_contract_service import aware
    from app.services.postback_relay_service import project_scope
    from app.services.operational_alert_service import send_operational_alert
    problems = []
    async with (sessions or get_db_session)() as db:
        oldest = await db.scalar(select(func.min(PostbackFollowup.created_at)).where(PostbackFollowup.status == "pending"))
        if oldest and (datetime.now(timezone.utc) - aware(oldest)).total_seconds() > max(1, settings.POSTBACK_RELAY_ALERT_PENDING_SECONDS):
            problems.append("followup_queue_stalled")
        if settings.POSTBACK_RELAY_ENABLED:
            scope = project_scope()
            active = select(PostbackEndpoint.id).join(Project, Project.id == PostbackEndpoint.project_id).where(
                PostbackEndpoint.is_active.is_(True), PostbackEndpoint.is_archived.is_(False),
                Project.is_deleted.is_(False), Project.status == "active").limit(1)
            if scope is not None:
                active = active.where(PostbackEndpoint.project_id.in_(scope))
            if await db.scalar(active):
                health = await db.scalar(select(PostbackRelayHealth).order_by(PostbackRelayHealth.seen_at.desc()).limit(1))
                if health is None or (datetime.now(timezone.utc) - aware(health.seen_at)).total_seconds() > max(1, settings.POSTBACK_RELAY_ALERT_HEARTBEAT_SECONDS):
                    problems.append("gateway_heartbeat_missing")
                elif health:
                    stats = health.stats_json
                    if stats.get("counts", {}).get("dead", 0) > 0:
                        problems.append("gateway_dead_deliveries")
                    if stats.get("oldest_pending_seconds", 0) > max(1, settings.POSTBACK_RELAY_ALERT_PENDING_SECONDS):
                        problems.append("gateway_queue_stalled")
                    if stats.get("free_bytes", 0) < max(0, settings.POSTBACK_RELAY_ALERT_FREE_BYTES):
                        problems.append("gateway_low_disk")
    for problem in problems:
        await send_operational_alert(component="postback_transport", title="Postback transport requires attention",
            dedupe_key=f"postback-transport:{problem}", details={"condition": problem})
    return {"problems": problems}


async def deliver_postback_followups_task(ctx=None, *, sessions=None, sender=None):
    factory = sessions or get_db_session
    async with factory() as db:
        # A worker may have died after a remote service accepted the request.
        await db.execute(update(PostbackFollowup).where(PostbackFollowup.status == "sending",
            PostbackFollowup.claimed_at < datetime.now(timezone.utc) - timedelta(minutes=5))
            .values(status="review", error="Worker stopped during external delivery; reconcile before retry"))
        await db.commit()
    claimed = 0
    started = time.monotonic()
    for _ in range(200):
        if time.monotonic() - started > 20:
            break
        async with factory() as db:
            job = await db.scalar(select(PostbackFollowup).where(PostbackFollowup.status == "pending")
                .order_by(PostbackFollowup.created_at).limit(1).with_for_update(skip_locked=True))
            if job is None:
                break
            job.status = "sending"; job.claimed_at = datetime.now(timezone.utc)
            job_id = job.id
            project_id, kind = job.project_id, job.kind
            await db.commit()
            claimed += 1
        try:
            async with factory() as db:
                job = await db.get(PostbackFollowup, job_id)
                if sender:
                    await sender(db, job)
                else:
                    payload = job.payload_json
                    if job.kind == "sheets_status":
                        from app.services.google_sheets_trigger_service import GoogleSheetsTriggerService
                        await GoogleSheetsTriggerService(db).enqueue_if_status_triggered(
                            lead_id=UUID(payload["lead_id"]), project_id=job.project_id,
                            status_id=UUID(payload["current_status_id"]), strict=True)
                    elif job.kind == "facebook_status":
                        from app.services.advertising_event_service import AdvertisingEventService
                        service = AdvertisingEventService(db)
                        service.strict_enqueue = True
                        await service.enqueue_status_change(lead_id=UUID(payload["lead_id"]),
                            previous_status_id=UUID(payload["previous_status_id"]), current_status_id=UUID(payload["current_status_id"]))
                    elif job.kind == "facebook_lifecycle":
                        from app.services.facebook_campaign_service import FacebookCampaignService
                        from app.core.facebook_events import facebook_mapping_for_source, facebook_mapping_has_trigger, FACEBOOK_AUTOMATIC_SOURCE_EVENTS
                        from app.models.lead_event import LeadEvent
                        from app.models.tracking import TrackingLink
                        event = await db.get(LeadEvent, UUID(payload["event_id"]))
                        if event is None:
                            raise ValueError("Postback event no longer exists")
                        link = await db.get(TrackingLink, event.tracking_link_id) if event.tracking_link_id else None
                        source = {"registration": "registration", "deposit": "sale", "redeposit": "resale"}[event.event_type]
                        mapping = facebook_mapping_for_source(link.fb_event_mappings_json, source) if link else None
                        if link and mapping and link.fb_campaign_enabled and link.fb_pixel_id and link.fb_capi_token and (
                            source in FACEBOOK_AUTOMATIC_SOURCE_EVENTS or facebook_mapping_has_trigger(mapping, trigger_type="funnel_action")):
                            helper = FacebookCampaignService(db); helper.strict_enqueue = True
                            lead = await helper._load_lead(event.lead_id)
                            reference = f"crm_rule:{source}:{payload['lifecycle_reference']}" if any(
                                t.get("type") in {"lead_status", "lead_tag"} for t in mapping.get("triggers", [])) else str(event.id)
                            await helper._enqueue_mapping(lead=lead, link=link, mapping=mapping, source_event=source,
                                event_reference=reference, event_time=int(event.occurred_at.timestamp()),
                                attribution_context=payload.get("fb_data") or {},
                                attribution_event_id=event.id,
                                extra_custom_data={**({"value": float(event.amount)} if event.amount is not None else {}),
                                    **({"currency": event.currency} if event.currency else {})})
                job.status = "done"
                await db.commit()
        except Exception as exc:
            async with factory() as db:
                await db.execute(update(PostbackFollowup).where(PostbackFollowup.id == job_id)
                    .values(status="review", error=type(exc).__name__))
                await db.commit()
            from app.services.operational_alert_service import send_operational_alert
            await send_operational_alert(component="postback_followup", title="Postback integration requires review",
                dedupe_key=f"postback-followup:{project_id}:{kind}", details={"job_id": str(job_id), "error_type": type(exc).__name__})
    return {"claimed": claimed}
