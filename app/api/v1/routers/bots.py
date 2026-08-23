from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.schemas.bot import (
    BotCreate,
    BotOut,
    BotStepOut,
    BotTelegramStatusOut,
    BotUpdate,
    BotWebhookOut,
    TelegramAccountCodeIn,
    TelegramAccountConnectIn,
    TelegramAccountConnectionOut,
    TelegramAccountPasswordIn,
)
from app.schemas.common import PaginatedResponse
from app.schemas.funnel import BotActiveFunnelOut, BotActiveFunnelSetIn
from app.schemas.lead_import import (
    BotLeadImportOut,
    LeadImportExecuteIn,
    LeadImportExecuteOut,
    LeadImportPreviewOut,
)
from app.services.bot_lead_import_service import BotLeadImportService
from app.services.bot_service import BotService
from app.services.funnel_service import FunnelService
from app.services.telegram_user_account_service import TelegramUserAccountService

router = APIRouter(tags=["bots"])


@router.get("/bots", response_model=PaginatedResponse[BotOut])
async def list_bots(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: Optional[UUID] = Query(default=None),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[BotOut]:
    items, total = await BotService(db).list_bots(
        project_id=project_id,
        limit=limit,
        offset=offset,
        actor=current_user,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/bots", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    data: BotCreate,
    current_project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    _ensure_bot_management_access(current_user)
    return await BotService(db).create_bot(project_id=current_project_id, data=data)


@router.get("/bot_steps", response_model=list[BotStepOut])
async def list_bot_steps(
    bot_id: UUID = Query(...),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> list[BotStepOut]:
    return await BotService(db).list_bot_steps(bot_id=bot_id, project_id=project_id)


@router.get("/bots/{bot_id}", response_model=BotOut)
async def get_bot(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    return await BotService(db).get_bot(bot_id=bot_id, project_id=project_id)


@router.get(
    "/bots/{bot_id}/telegram-account",
    response_model=TelegramAccountConnectionOut,
)
async def get_telegram_account_connection(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramAccountConnectionOut:
    _ensure_telegram_account_management_access(current_user)
    return await TelegramUserAccountService(db).get_status(
        bot_id=bot_id,
        project_id=project_id,
    )


@router.post(
    "/bots/{bot_id}/telegram-account/request-code",
    response_model=TelegramAccountConnectionOut,
)
async def request_telegram_account_code(
    bot_id: UUID,
    data: TelegramAccountConnectIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramAccountConnectionOut:
    _ensure_telegram_account_management_access(current_user)
    return await TelegramUserAccountService(db).request_login_code(
        bot_id=bot_id,
        project_id=project_id,
        data=data,
        actor=current_user,
    )


@router.post(
    "/bots/{bot_id}/telegram-account/confirm-code",
    response_model=TelegramAccountConnectionOut,
)
async def confirm_telegram_account_code(
    bot_id: UUID,
    data: TelegramAccountCodeIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramAccountConnectionOut:
    _ensure_telegram_account_management_access(current_user)
    return await TelegramUserAccountService(db).confirm_code(
        bot_id=bot_id,
        project_id=project_id,
        code=data.code,
        actor=current_user,
    )


@router.post(
    "/bots/{bot_id}/telegram-account/confirm-password",
    response_model=TelegramAccountConnectionOut,
)
async def confirm_telegram_account_password(
    bot_id: UUID,
    data: TelegramAccountPasswordIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramAccountConnectionOut:
    _ensure_telegram_account_management_access(current_user)
    return await TelegramUserAccountService(db).confirm_password(
        bot_id=bot_id,
        project_id=project_id,
        password=data.password,
        actor=current_user,
    )


@router.post(
    "/bots/{bot_id}/telegram-account/sync",
    response_model=TelegramAccountConnectionOut,
)
async def sync_telegram_account(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramAccountConnectionOut:
    _ensure_telegram_account_management_access(current_user)
    return await TelegramUserAccountService(db).sync_identity(
        bot_id=bot_id,
        project_id=project_id,
        actor=current_user,
    )


@router.delete(
    "/bots/{bot_id}/telegram-account",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_telegram_account(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_telegram_account_management_access(current_user)
    await TelegramUserAccountService(db).disconnect(
        bot_id=bot_id,
        project_id=project_id,
        actor=current_user,
    )


@router.get("/bots/{bot_id}/lead-imports", response_model=list[BotLeadImportOut])
async def list_bot_lead_imports(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BotLeadImportOut]:
    return await BotLeadImportService(db).list_imports(
        project_id=project_id,
        bot_id=bot_id,
        actor=current_user,
    )


@router.post(
    "/bots/{bot_id}/lead-imports",
    response_model=BotLeadImportOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_bot_lead_import_template(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotLeadImportOut:
    return await BotLeadImportService(db).create_template(
        project_id=project_id,
        bot_id=bot_id,
        actor=current_user,
    )


@router.post(
    "/bots/{bot_id}/lead-imports/{import_id}/preview",
    response_model=LeadImportPreviewOut,
)
async def preview_bot_lead_import(
    bot_id: UUID,
    import_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadImportPreviewOut:
    return await BotLeadImportService(db).preview_import(
        project_id=project_id,
        bot_id=bot_id,
        import_id=import_id,
        actor=current_user,
    )


@router.post(
    "/bots/{bot_id}/lead-imports/{import_id}/execute",
    response_model=LeadImportExecuteOut,
)
async def execute_bot_lead_import(
    bot_id: UUID,
    import_id: UUID,
    data: LeadImportExecuteIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadImportExecuteOut:
    return await BotLeadImportService(db).execute_import(
        project_id=project_id,
        bot_id=bot_id,
        import_id=import_id,
        preview_checksum=data.preview_checksum,
        actor=current_user,
    )


@router.get("/bots/{bot_id}/active-funnel", response_model=BotActiveFunnelOut)
async def get_bot_active_funnel(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotActiveFunnelOut:
    return await FunnelService(db).get_active_funnel_for_bot(
        bot_id=bot_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/bots/{bot_id}/active-funnel", response_model=BotActiveFunnelOut)
async def set_bot_active_funnel(
    bot_id: UUID,
    data: BotActiveFunnelSetIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotActiveFunnelOut:
    return await FunnelService(db).set_active_funnel_for_bot(
        bot_id=bot_id,
        project_id=project_id,
        data=data,
        current_user=current_user,
    )


@router.patch("/bots/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: UUID,
    data: BotUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    _ensure_bot_management_access(current_user)
    service = BotService(db)
    telegram_profile_fields = {"telegram_description", "telegram_about"}
    profile_update_required = False
    if telegram_profile_fields & data.model_fields_set:
        current = await service.get_bot(bot_id=bot_id, project_id=project_id)
        for field_name in telegram_profile_fields & data.model_fields_set:
            requested = getattr(data, field_name)
            normalized_requested = requested.strip() if requested and requested.strip() else None
            if normalized_requested != getattr(current, field_name):
                profile_update_required = True
                break

    updated = await service.update_bot(
        bot_id=bot_id,
        project_id=project_id,
        data=data,
        actor=current_user,
    )
    if profile_update_required:
        try:
            await service.update_bot_profile_on_telegram(bot_id, actor=current_user)
        except HTTPException as exc:
            if "telegram_token" not in data.model_fields_set:
                raise
            profile_warning = (
                "Token сохранён, но описание профиля Telegram не синхронизировано: "
                f"{exc.detail}"
            )
            combined_warning = " ".join(
                part for part in (updated.telegram_setup_warning, profile_warning) if part
            )
            return updated.model_copy(
                update={"telegram_setup_warning": combined_warning}
            )
    return updated


@router.post("/bots/{bot_id}/avatar", status_code=status.HTTP_200_OK)
async def upload_bot_avatar(
    bot_id: UUID,
    file: UploadFile = File(...),
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    _ensure_bot_management_access(current_user)
    if file.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telegram bot profile photo must be a JPEG image",
        )
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Avatar file is empty",
        )
    await BotService(db).set_bot_profile_photo(
        bot_id=bot_id,
        photo_bytes=file_bytes,
        actor=current_user,
        file_name=file.filename or "bot_profile.jpg",
        mime_type=file.content_type or "image/jpeg",
    )
    return {"ok": True}


@router.get("/bots/{bot_id}/avatar", response_class=Response)
async def get_bot_avatar(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content, media_type = await BotService(db).get_bot_profile_photo(
        bot_id=bot_id,
        project_id=project_id,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/bots/{bot_id}/audit-logs/export", response_class=Response)
async def export_bot_audit_logs(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await BotService(db).get_bot(bot_id=bot_id, project_id=project_id)
    csv_bytes = await BotService(db).export_bot_audit_logs_to_csv(bot_id)
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bot_audit_logs.csv"'},
    )


@router.delete("/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_bot_management_access(current_user)
    await BotService(db).delete_bot(bot_id=bot_id, project_id=project_id)


@router.post("/bots/{bot_id}/webhook", response_model=BotWebhookOut)
async def set_bot_webhook(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotWebhookOut:
    _ensure_bot_management_access(current_user)
    return await BotService(db).set_webhook(bot_id=bot_id, project_id=project_id)


@router.post("/bots/{bot_id}/sync-telegram-identity", response_model=BotOut)
async def sync_bot_telegram_identity(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotOut:
    _ensure_bot_management_access(current_user)
    return await BotService(db).sync_bot_identity_from_token(
        bot_id=bot_id,
        project_id=project_id,
    )


@router.get("/bots/{bot_id}/telegram-status", response_model=BotTelegramStatusOut)
async def get_bot_telegram_status(
    bot_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotTelegramStatusOut:
    _ensure_bot_management_access(current_user)
    return await BotService(db).telegram_status(bot_id=bot_id, project_id=project_id)


def _ensure_bot_management_access(current_user: Any) -> None:
    if current_user.role_name not in {
        RoleName.SUPER_ADMIN,
        RoleName.ADMIN,
        RoleName.OPERATOR,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current user cannot manage bots",
        )


def _ensure_telegram_account_management_access(current_user: Any) -> None:
    if current_user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can authorize a Telegram account",
        )
