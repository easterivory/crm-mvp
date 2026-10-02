from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.dependencies import get_current_user, get_db
from app.models.traffic_quality import TrafficQualityState, TrafficQualityDelivery
from app.models.audit_log import AuditLog
from app.models.tracking import TrackingLink
from app.core.constants import RoleName
from app.schemas.traffic_quality import QualityConfig, QualityOverrides, effective_rules
from app.services.traffic_quality_service import TrafficQualityService

router = APIRouter(prefix="/traffic-quality", tags=["traffic-quality"])


@router.get("/projects/{project_id}")
async def get_config(project_id: UUID, actor=Depends(get_current_user), db=Depends(get_db)):
    service = TrafficQualityService(db)
    await service.project(project_id, actor)
    return await service.config(project_id)


@router.put("/projects/{project_id}")
async def put_config(project_id: UUID, data: QualityConfig, actor=Depends(get_current_user), db=Depends(get_db)):
    return await TrafficQualityService(db).save_config(project_id, actor, data)


@router.get("/links/{link_id}")
async def get_link_config(link_id: UUID, actor=Depends(get_current_user), db=Depends(get_db)):
    service = TrafficQualityService(db)
    link = await service.link(link_id, actor)
    config, overrides = await service.config(link.project_id), await service.overrides(link.id)
    return {"project": config, "overrides": overrides, "effective_rules": effective_rules(config, overrides)}


@router.put("/links/{link_id}")
async def put_link_config(link_id: UUID, data: QualityOverrides, actor=Depends(get_current_user), db=Depends(get_db)):
    return await TrafficQualityService(db).save_overrides(link_id, actor, data)


class PreviewRequest(BaseModel):
    config: QualityConfig
    link_id: UUID | None = None
    overrides: QualityOverrides | None = None
    offset: int = Field(default=0, ge=0)


@router.post("/projects/{project_id}/preview")
async def preview(project_id: UUID, data: PreviewRequest, actor=Depends(get_current_user), db=Depends(get_db)):
    try:
        return await TrafficQualityService(db).preview(project_id, actor, data.config, data.link_id, data.overrides, data.offset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/projects/{project_id}/states")
async def states(project_id: UUID, link_id: UUID | None = None, offset: int = Query(0, ge=0), actor=Depends(get_current_user), db=Depends(get_db)):
    await TrafficQualityService(db).project(project_id, actor)
    stmt = select(TrafficQualityState, TrackingLink.title).join(TrackingLink, TrackingLink.id == TrafficQualityState.link_id).where(TrackingLink.project_id == project_id)
    if actor.role_name == RoleName.BUYER:
        stmt = stmt.where(TrackingLink.buyer_id == actor.id)
    if link_id:
        stmt = stmt.where(TrackingLink.id == link_id)
    rows = (await db.execute(stmt.order_by(TrafficQualityState.checked_at.desc(), TrafficQualityState.link_id, TrafficQualityState.rule_id).offset(offset).limit(101))).all()
    return {"items": [{"link_id": s.link_id, "link_title": title, "rule_id": s.rule_id, "active": s.active,
                        "status": s.status, "checked_at": s.checked_at, "snapshot": s.snapshot} for s, title in rows[:100]],
            "next_offset": offset + 100 if len(rows) > 100 else None}


class Acknowledge(BaseModel):
    hours: int = Field(default=24, ge=1, le=72)


@router.post("/links/{link_id}/acknowledge")
async def acknowledge(link_id: UUID, data: Acknowledge, actor=Depends(get_current_user), db=Depends(get_db)):
    return await TrafficQualityService(db).acknowledge(link_id, actor, data.hours)


@router.get("/projects/{project_id}/history")
async def history(project_id: UUID, link_id: UUID | None = None, offset: int = Query(0, ge=0), actor=Depends(get_current_user), db=Depends(get_db)):
    await TrafficQualityService(db).project(project_id, actor, admin_only=True)
    stmt = select(TrafficQualityDelivery).where(TrafficQualityDelivery.project_id == project_id)
    if link_id:
        stmt = stmt.where(TrafficQualityDelivery.link_id == link_id)
    rows = (await db.scalars(stmt.order_by(TrafficQualityDelivery.created_at.desc(), TrafficQualityDelivery.id).offset(offset).limit(51))).all()
    return {"items": [{"id": r.id, "link_id": r.link_id, "status": r.status, "attempts": r.attempts,
            "error": r.error, "created_at": r.created_at, "sent_at": r.sent_at, "body": r.body} for r in rows[:50]],
            "next_offset": offset + 50 if len(rows) > 50 else None}


@router.get("/projects/{project_id}/audit")
async def audit(project_id: UUID, offset: int = Query(0, ge=0), actor=Depends(get_current_user), db=Depends(get_db)):
    await TrafficQualityService(db).project(project_id, actor, admin_only=True)
    rows = (await db.scalars(select(AuditLog).where(AuditLog.project_id == project_id,
        AuditLog.action == "traffic_quality.updated").order_by(AuditLog.created_at.desc(), AuditLog.id).offset(offset).limit(50))).all()
    return [{"at": r.created_at, "actor_id": r.actor_id, "entity_type": r.entity_type, "entity_id": r.entity_id, "changes": r.meta} for r in rows]
