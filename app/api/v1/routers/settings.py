from __future__ import annotations

import logging
import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from arq import create_pool
from arq.jobs import Job, JobStatus
from fastapi.responses import FileResponse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_root_user, get_current_user, get_db
from app.core.constants import RoleName
from app.core.redis import get_redis
from app.models.user import User
from app.schemas.system_setting import (
    BuyerBotConfigOut,
    BuyerBotConfigUpdate,
    BackupJobOut,
    BackupDownloadOut,
    FunnelStartRecoveryIn,
    FunnelStartRecoveryOut,
    ServerLogExportOut,
    SystemGlobalConfigOut,
    SystemGlobalConfigUpdate,
    TranslationProviderConfigOut,
    TranslationProviderConfigUpdate,
)
from app.services.system_setting_service import SystemSettingService
from app.services.translation_languages import LANGUAGES_KEY, TranslationLanguage, get_languages
from app.services.funnel_start_recovery_service import FunnelStartRecoveryService
from app.services.backup_queue import enqueue_manual_backup, enqueue_download_backup, backup_redis_settings
from app.services.backup_download_service import resolve_download
from app.core.arq_queues import BACKUP_QUEUE_NAME
from app.services.server_log_service import (
    ServerLogExportError,
    collect_recent_server_logs,
    send_server_logs_to_telegram,
)

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("/translation/languages", response_model=list[TranslationLanguage])
async def list_translation_languages(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TranslationLanguage]:
    return await get_languages(SystemSettingService(db))


@router.post("/translation/languages", response_model=list[TranslationLanguage])
async def add_translation_language(
    data: TranslationLanguage,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TranslationLanguage]:
    _ensure_settings_admin(current_user)
    # Serialize read/modify/write, including the first catalog creation.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": LANGUAGES_KEY})
    service = SystemSettingService(db)
    custom = json.loads(await service.get_value(LANGUAGES_KEY) or "{}")
    if data.value not in custom and len(custom) >= 300:
        raise HTTPException(status_code=422, detail="Достигнут лимит языков")
    custom[data.value] = data.label
    await service.set_value(LANGUAGES_KEY, json.dumps(custom, ensure_ascii=False))
    await db.commit()
    return await get_languages(service)


@router.get("/buyer-bot", response_model=BuyerBotConfigOut)
async def get_buyer_bot_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BuyerBotConfigOut:
    _ensure_settings_admin(current_user)
    config = await SystemSettingService(db).get_buyer_bot_config()
    return BuyerBotConfigOut(token=config.token, username=config.username)


@router.patch("/buyer-bot", response_model=BuyerBotConfigOut)
async def update_buyer_bot_settings(
    data: BuyerBotConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BuyerBotConfigOut:
    _ensure_settings_admin(current_user)
    service = SystemSettingService(db)
    current = await service.get_buyer_bot_config()
    values = data.model_dump(exclude_unset=True)
    config = await service.set_buyer_bot_config(
        token=values.get("token", current.token),
        username=values.get("username", current.username),
    )
    await db.commit()
    return BuyerBotConfigOut(token=config.token, username=config.username)


@router.get("/translation", response_model=TranslationProviderConfigOut)
async def get_translation_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TranslationProviderConfigOut:
    _ensure_settings_admin(current_user)
    config = await SystemSettingService(db).get_translation_provider_config()
    return TranslationProviderConfigOut(
        provider=config.provider,
        api_key=config.api_key,
        base_url=config.base_url,
    )


@router.patch("/translation", response_model=TranslationProviderConfigOut)
async def update_translation_settings(
    data: TranslationProviderConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TranslationProviderConfigOut:
    _ensure_settings_admin(current_user)
    service = SystemSettingService(db)
    current = await service.get_translation_provider_config()
    values = data.model_dump(exclude_unset=True)
    config = await service.set_translation_provider_config(
        provider=values.get("provider", current.provider),
        api_key=values.get("api_key", current.api_key),
        base_url=values.get("base_url", current.base_url),
    )
    await db.commit()
    return TranslationProviderConfigOut(
        provider=config.provider,
        api_key=config.api_key,
        base_url=config.base_url,
    )


@router.get("/global", response_model=SystemGlobalConfigOut)
async def get_global_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SystemGlobalConfigOut:
    _ensure_super_admin(current_user)
    config = await SystemSettingService(db).get_global_config()
    return SystemGlobalConfigOut(
        tg_backup_bot_token=config.tg_backup_bot_token,
        tg_backup_channel_id=config.tg_backup_channel_id,
        is_tg_backup_enabled=config.is_tg_backup_enabled,
        admin_bot_token=config.admin_bot_token,
        channel_join_auto_start=config.channel_join_auto_start,
        channel_join_auto_approve=config.channel_join_auto_approve,
    )


@router.patch("/global", response_model=SystemGlobalConfigOut)
async def update_global_settings(
    data: SystemGlobalConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SystemGlobalConfigOut:
    _ensure_super_admin(current_user)
    service = SystemSettingService(db)
    current = await service.get_global_config()
    values = data.model_dump(exclude_unset=True)
    backup_token = values.get("tg_backup_bot_token", current.tg_backup_bot_token)
    backup_channel_id = values.get("tg_backup_channel_id", current.tg_backup_channel_id)
    backup_enabled = values.get("is_tg_backup_enabled", current.is_tg_backup_enabled)
    if backup_enabled and (not backup_token or not backup_channel_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Backup bot token and channel ID are required when Telegram backup is enabled",
        )
    config = await service.set_global_config(
        tg_backup_bot_token=backup_token,
        tg_backup_channel_id=backup_channel_id,
        is_tg_backup_enabled=backup_enabled,
        admin_bot_token=values.get("admin_bot_token", current.admin_bot_token),
        channel_join_auto_start=values.get(
            "channel_join_auto_start",
            current.channel_join_auto_start,
        ),
        channel_join_auto_approve=values.get(
            "channel_join_auto_approve",
            current.channel_join_auto_approve,
        ),
    )
    await db.commit()
    return SystemGlobalConfigOut(
        tg_backup_bot_token=config.tg_backup_bot_token,
        tg_backup_channel_id=config.tg_backup_channel_id,
        is_tg_backup_enabled=config.is_tg_backup_enabled,
        admin_bot_token=config.admin_bot_token,
        channel_join_auto_start=config.channel_join_auto_start,
        channel_join_auto_approve=config.channel_join_auto_approve,
    )


@router.post("/global/backup/run", response_model=BackupJobOut, status_code=status.HTTP_202_ACCEPTED)
async def run_manual_backup(
    _root_user: User = Depends(get_current_root_user),
) -> BackupJobOut:
    try:
        return BackupJobOut(job_id=await enqueue_manual_backup())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backup queue is unavailable",
        ) from exc


@router.post("/global/backup/download", response_model=BackupJobOut, status_code=202)
async def prepare_backup_download(
    root: User = Depends(get_current_root_user),
) -> BackupJobOut:
    redis = await get_redis()
    if not await redis.set(f"backup-download:cooldown:{root.id}", "1", nx=True, ex=60):
        raise HTTPException(status_code=429, detail="Бэкап можно создавать не чаще одного раза в минуту")
    try:
        return BackupJobOut(job_id=await enqueue_download_backup())
    except Exception as exc:
        logger.exception("Could not enqueue backup download")
        raise HTTPException(status_code=503, detail="Очередь бэкапов недоступна") from exc


async def _backup_download_status(job_id: UUID) -> BackupDownloadOut:
    redis = await create_pool(backup_redis_settings())
    try:
        job = Job(f"download-backup:{job_id}", redis, _queue_name=BACKUP_QUEUE_NAME)
        result = await job.result_info()
        if result is not None:
            if not result.success:
                return BackupDownloadOut(status="failed")
            return BackupDownloadOut(status="ready", **result.result)
        state = await job.status()
        if state == JobStatus.not_found:
            raise HTTPException(status_code=404, detail="Бэкап не найден или срок скачивания истёк")
        return BackupDownloadOut(status="in_progress" if state == JobStatus.in_progress else "queued")
    finally:
        await redis.close()


@router.get("/global/backup/download/{job_id}", response_model=BackupDownloadOut)
async def backup_download_status(
    job_id: UUID,
    _root: User = Depends(get_current_root_user),
) -> BackupDownloadOut:
    return await _backup_download_status(job_id)


@router.get("/global/backup/download/{job_id}/file")
async def download_backup_file(
    job_id: UUID,
    _root: User = Depends(get_current_root_user),
) -> FileResponse:
    result = await _backup_download_status(job_id)
    if result.status != "ready" or not result.file_name:
        raise HTTPException(status_code=409, detail="Бэкап ещё не готов или завершился ошибкой")
    try:
        path = resolve_download(job_id, result.file_name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=410, detail="Архив недоступен. Создайте новый бэкап.") from exc
    return FileResponse(
        path, filename=result.file_name, media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/global/logs/export", response_model=ServerLogExportOut)
async def export_recent_server_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ServerLogExportOut:
    _ensure_super_admin(current_user)
    config = await SystemSettingService(db).get_effective_global_config()
    if not config.tg_backup_bot_token or not config.tg_backup_channel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Сначала настройте backup-бота и ID канала",
        )

    redis = await get_redis()
    lock_key = "system:server-log-export:cooldown"
    acquired = await redis.set(lock_key, str(current_user.id), ex=60, nx=True)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Выгрузку логов можно запускать не чаще одного раза в минуту",
        )

    content = collect_recent_server_logs(minutes=30)
    try:
        file_name = await send_server_logs_to_telegram(
            content,
            bot_token=config.tg_backup_bot_token,
            chat_id=config.tg_backup_channel_id,
            minutes=30,
        )
    except ServerLogExportError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    logger.info(
        "Super admin exported recent server logs user_id=%s file_name=%s size_bytes=%s",
        current_user.id,
        file_name,
        len(content),
    )
    return ServerLogExportOut(
        file_name=file_name,
        size_bytes=len(content),
        period_minutes=30,
    )


@router.post(
    "/global/funnels/recover-starts",
    response_model=FunnelStartRecoveryOut,
)
async def recover_missed_funnel_starts(
    data: FunnelStartRecoveryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelStartRecoveryOut:
    _ensure_super_admin(current_user)
    redis = await get_redis()
    lock_key = "system:funnel-start-recovery:cooldown"
    acquired = await redis.set(lock_key, str(current_user.id), ex=30, nx=True)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Восстановление уже запущено. Повторите через 30 секунд.",
        )

    scope = (
        f"manual-{current_user.id}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )
    result = await FunnelStartRecoveryService(db).recover(
        lookback_hours=data.lookback_hours,
        limit=data.limit,
        job_scope=scope,
    )
    await db.commit()
    logger.info(
        "Super admin requested funnel start recovery user_id=%s lookback_hours=%s "
        "eligible=%s scheduled=%s failed=%s",
        current_user.id,
        result.lookback_hours,
        result.eligible,
        result.scheduled,
        result.queue_failed,
    )
    return FunnelStartRecoveryOut(
        **asdict(result),
        scheduled=result.scheduled,
    )


def _ensure_settings_admin(current_user: User) -> None:
    if current_user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin/super_admin can manage system settings",
        )


def _ensure_super_admin(current_user: User) -> None:
    if current_user.role_name != RoleName.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin can manage global settings",
        )
