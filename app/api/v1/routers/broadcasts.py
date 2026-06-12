from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.schemas.broadcast import (
    AudiencePreviewRequest,
    AudiencePreviewResponse,
    BroadcastActionResponse,
    BroadcastCreate,
    BroadcastDeliveryAnalytics,
    BroadcastErrorLogRow,
    BroadcastOut,
    BroadcastReport,
    BroadcastScheduleRequest,
    BroadcastTemplateCreate,
    BroadcastTemplateOut,
    BroadcastTemplateUpdate,
    BroadcastUpdate,
    BroadcastUploadOut,
    SendNowRequest,
)
from app.schemas.common import PaginatedResponse
from app.services.broadcast_service import BroadcastService
from app.workers.broadcast_worker import enqueue_broadcast_job

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])


@router.get("", response_model=PaginatedResponse[BroadcastOut])
async def list_broadcasts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[BroadcastOut]:
    items, total = await BroadcastService(db).list_broadcasts(
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=BroadcastOut, status_code=status.HTTP_201_CREATED)
async def create_broadcast(
    data: BroadcastCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastOut:
    return await BroadcastService(db).create_broadcast(
        actor=current_user,
        project_id=project_id,
        data=data,
    )


@router.post("/uploads", response_model=BroadcastUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_broadcast_media(
    file: UploadFile = File(...),
    media_type: str | None = Form(default=None),
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastUploadOut:
    return await BroadcastService(db).upload_media(
        actor=current_user,
        project_id=project_id,
        file=file,
        media_type=media_type,
    )


@router.get("/templates", response_model=list[BroadcastTemplateOut])
async def list_broadcast_templates(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> list[BroadcastTemplateOut]:
    return await BroadcastService(db).list_templates(
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


@router.post("/templates", response_model=BroadcastTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_broadcast_template(
    data: BroadcastTemplateCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastTemplateOut:
    return await BroadcastService(db).create_template(
        actor=current_user,
        project_id=project_id,
        data=data,
    )


@router.patch("/templates/{template_id}", response_model=BroadcastTemplateOut)
async def update_broadcast_template(
    template_id: UUID,
    data: BroadcastTemplateUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastTemplateOut:
    return await BroadcastService(db).update_template(
        template_id=template_id,
        actor=current_user,
        project_id=project_id,
        data=data,
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_broadcast_template(
    template_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await BroadcastService(db).delete_template(
        template_id=template_id,
        actor=current_user,
        project_id=project_id,
    )


@router.get("/{broadcast_id}", response_model=BroadcastOut)
async def get_broadcast(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BroadcastOut:
    return await BroadcastService(db).get_broadcast(broadcast_id, project_id)


@router.delete("/{broadcast_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_broadcast(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await BroadcastService(db).delete_broadcast(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
    )


@router.delete("/{broadcast_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanently_delete_broadcast(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await BroadcastService(db).permanently_delete_broadcast(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
    )


@router.get("/{broadcast_id}/error-log", response_model=list[BroadcastErrorLogRow])
async def get_broadcast_error_log(
    broadcast_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> list[BroadcastErrorLogRow]:
    return await BroadcastService(db).error_log(
        broadcast_id=broadcast_id,
        project_id=project_id,
        limit=limit,
    )


@router.get("/{broadcast_id}/detailed-analytics", response_model=BroadcastDeliveryAnalytics)
async def get_broadcast_detailed_analytics(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BroadcastDeliveryAnalytics:
    return await BroadcastService(db).delivery_analytics(
        broadcast_id=broadcast_id,
        project_id=project_id,
    )


@router.get("/{broadcast_id}/report", response_model=None)
async def get_broadcast_report(
    broadcast_id: UUID,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BroadcastReport | Response:
    service = BroadcastService(db)
    if format == "csv":
        csv_body = await service.error_csv(broadcast_id, project_id)
        return Response(
            content=csv_body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="broadcast-{broadcast_id}-errors.csv"'
            },
        )
    return await service.report(broadcast_id, project_id)


@router.patch("/{broadcast_id}", response_model=BroadcastOut)
async def update_broadcast(
    broadcast_id: UUID,
    data: BroadcastUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastOut:
    return await BroadcastService(db).update_broadcast(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
        data=data,
    )


@router.post("/audience/preview", response_model=AudiencePreviewResponse)
async def preview_audience(
    data: AudiencePreviewRequest,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> AudiencePreviewResponse:
    return await BroadcastService(db).preview_audience(project_id=project_id, data=data)


@router.post("/{broadcast_id}/audience-preview", response_model=AudiencePreviewResponse)
async def preview_broadcast_audience(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> AudiencePreviewResponse:
    return await BroadcastService(db).preview_broadcast_audience(
        broadcast_id=broadcast_id,
        project_id=project_id,
    )


@router.post("/{broadcast_id}/schedule", response_model=BroadcastActionResponse)
async def schedule_broadcast(
    broadcast_id: UUID,
    data: BroadcastScheduleRequest,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastActionResponse:
    return await BroadcastService(db).schedule(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
        data=data,
    )


@router.post("/{broadcast_id}/send-now", response_model=BroadcastActionResponse)
async def send_broadcast_now(
    broadcast_id: UUID,
    data: SendNowRequest | None = None,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastActionResponse:
    result = await BroadcastService(db).send_now(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
        data=data,
    )
    await db.commit()
    await enqueue_broadcast_job(result.broadcast.id, project_id)
    return result


@router.post("/{broadcast_id}/cancel", response_model=BroadcastOut)
async def cancel_broadcast(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastOut:
    return await BroadcastService(db).cancel(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
    )


@router.post("/{broadcast_id}/pause", response_model=BroadcastOut)
async def pause_broadcast(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastOut:
    return await BroadcastService(db).pause(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
    )


@router.post("/{broadcast_id}/resume", response_model=BroadcastOut)
async def resume_broadcast(
    broadcast_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastOut:
    result = await BroadcastService(db).resume(
        broadcast_id=broadcast_id,
        actor=current_user,
        project_id=project_id,
    )
    await db.commit()
    await enqueue_broadcast_job(result.id, project_id)
    return result
