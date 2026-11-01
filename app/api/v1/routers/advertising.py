from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.models.advertising import AdvertisingConfig, AdvertisingSlot, AdvertisingEnrollment, AdvertisingDelivery, AdvertisingAudit
from app.models.chat import Chat
from app.models.tracking import TrackingLink
from app.schemas.advertising import AdvertisingSettings, SlotWrite, BackfillRequest
from app.services.advertising_service import AdvertisingService, now

router = APIRouter(prefix="/advertising", tags=["advertising"])


@router.get("/bot")
async def bot_settings(user=Depends(get_current_user), db=Depends(get_db)):
    from app.services.advertising_bot import AdvertisingBotConfig
    if user.role_name != RoleName.SUPER_ADMIN:
        raise HTTPException(403)
    service = AdvertisingBotConfig(db)
    return service.public(await service.read())


from app.api.v1.routers.info_bot import InfoBotSettings


@router.patch("/bot")
async def save_bot_settings(data: InfoBotSettings, user=Depends(get_current_user), db=Depends(get_db)):
    import json
    import re
    from sqlalchemy import text
    from app.models.bot import Bot
    from app.services.advertising_bot import AdvertisingBotConfig, AD_BOT_KEY
    from app.services.admin_bot_service import AdminTelegramClient
    from app.services.ai_credential_service import AICredentialService
    from app.services.info_bot_config import InfoBotConfigService
    from app.services.system_setting_service import SystemSettingService
    if user.role_name != RoleName.SUPER_ADMIN:
        raise HTTPException(403)
    token = (data.token or "").strip()
    profile = None
    if token:
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise HTTPException(422, "Неверный токен")
        await db.rollback()
        client = AdminTelegramClient(token)
        try:
            profile = await client.get_me()
            webhook = await client._post("getWebhookInfo", {})
            if (webhook.get("result") or {}).get("url"):
                raise HTTPException(422, "Используйте отдельного бота без webhook")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Не удалось проверить Telegram-бота") from None
        finally:
            await client.close()
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "crm_management_bot_settings"})
    service = AdvertisingBotConfig(db)
    config = await service.read()
    if token:
        system = SystemSettingService(db)
        global_cfg = await system.get_effective_global_config()
        buyer = await system.get_effective_buyer_bot_config()
        info = await InfoBotConfigService(db).read()
        info_token = AICredentialService().decrypt(info["encrypted_token"]) if info.get("encrypted_token") else None
        bot_id = token.split(":", 1)[0]
        other = (global_cfg.admin_bot_token, global_cfg.tg_backup_bot_token, buyer.token, info_token)
        exists = await db.scalar(select(Bot.id).where(Bot.telegram_token.like(f"{bot_id}:%")).limit(1))
        if exists or any(t and t.split(":", 1)[0] == bot_id for t in other):
            raise HTTPException(422, "Этот бот уже используется CRM. Нужен отдельный")
        config.update(encrypted_token=AICredentialService().encrypt(token), username=profile.get("username"))
    elif data.clear_token:
        config = {}
    if data.enabled and not config.get("encrypted_token"):
        raise HTTPException(422, "Укажите токен")
    config["enabled"] = data.enabled
    await service.settings.set_value(AD_BOT_KEY, json.dumps(config))
    return service.public(config)


def require_admin(user=Depends(get_current_user)):
    if user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(403, "Доступ только администраторам")
    return user


async def scenario_service(scenario_id: UUID | None = None,
    project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db)):
    service = AdvertisingService(db, scenario_id)
    await service.config(project_id)
    return service


@router.get("/scenarios")
async def scenarios(project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db)):
    rows = await AdvertisingService(db).scenarios(project_id)
    result = [{"id": r.id, "name": r.name, "enabled": r.enabled,
        "bot_ids": r.settings_json.get("bot_ids", [])} for r in rows]
    if not any(r.id == project_id for r in rows):
        result.insert(0, {"id": project_id, "name": "Основной", "enabled": False, "bot_ids": []})
    return result


from pydantic import BaseModel, Field


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.post("/scenarios")
async def create_scenario(data: ScenarioCreate, project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db)):
    return await AdvertisingService(db).create_scenario(project_id, data.name, user.id)


@router.get("/availability")
async def availability(project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db)):
    return {"enabled": any(r.enabled for r in await AdvertisingService(db).scenarios(project_id))}


@router.get("/settings")
async def settings(project_id=Depends(get_current_project_id), service=Depends(scenario_service)):
    return await service.config(project_id)


@router.put("/settings")
async def save_settings(data: AdvertisingSettings, project_id=Depends(get_current_project_id), user=Depends(require_admin), service=Depends(scenario_service)):
    return await service.save_config(project_id, data, user.id)


@router.get("/slots")
async def slots(project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    return list((await db.scalars(select(AdvertisingSlot).where(AdvertisingSlot.project_id == project_id)
        .where(AdvertisingSlot.scenario_id == service.scope(project_id))
        .order_by(AdvertisingSlot.position, AdvertisingSlot.id))).all())


@router.get("/media/{upload_id}")
async def media_preview(upload_id: UUID, project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db)):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.models.broadcast import BroadcastUpload
    from app.core.config import settings
    upload = await db.get(BroadcastUpload, upload_id)
    if not upload or upload.project_id != project_id:
        raise HTTPException(404)
    path = Path(upload.storage_path).resolve()
    if not path.is_relative_to(Path(settings.BROADCAST_UPLOAD_STORAGE_PATH).resolve()) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=upload.mime_type, headers={"Cache-Control": "private, max-age=300"})


@router.post("/slots")
async def create_slot(data: SlotWrite, project_id=Depends(get_current_project_id), user=Depends(require_admin), service=Depends(scenario_service)):
    return await service.save_slot(project_id, data, user.id)


@router.put("/slots/{slot_id}")
async def save_slot(slot_id: UUID, data: SlotWrite, project_id=Depends(get_current_project_id), user=Depends(require_admin), service=Depends(scenario_service)):
    return await service.save_slot(project_id, data, user.id, slot_id)


@router.get("/tracking")
async def tracking(start: datetime, end: datetime, bot_id: UUID | None = None,
    project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise HTTPException(422, "Укажите диапазон дат с часовым поясом")
    conditions = [AdvertisingEnrollment.project_id == project_id,
        AdvertisingEnrollment.scenario_id == service.scope(project_id),
        AdvertisingEnrollment.created_at >= start, AdvertisingEnrollment.created_at < end]
    if bot_id:
        conditions.append(Chat.bot_id == bot_id)
    base = select(AdvertisingEnrollment.id).join(Chat, Chat.id == AdvertisingEnrollment.chat_id).where(*conditions)
    counts = (await db.execute(select(AdvertisingEnrollment.status, func.count()).where(
        AdvertisingEnrollment.id.in_(base)).group_by(AdvertisingEnrollment.status))).all()
    slot_counts = (await db.execute(select(AdvertisingDelivery.slot_id, AdvertisingSlot.name,
        AdvertisingDelivery.status, func.count()).join(AdvertisingSlot, AdvertisingSlot.id == AdvertisingDelivery.slot_id)
        .where(AdvertisingDelivery.enrollment_id.in_(base))
        .group_by(AdvertisingDelivery.slot_id, AdvertisingSlot.name, AdvertisingDelivery.status))).all()
    sources = (await db.execute(select(Chat.tracking_link_id, func.count(), TrackingLink.name, TrackingLink.code).join(
        AdvertisingEnrollment, AdvertisingEnrollment.chat_id == Chat.id)
        .outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(*conditions)
        .group_by(Chat.tracking_link_id, TrackingLink.name, TrackingLink.code))).all()
    return {"cohort_counts": dict(counts), "slots": [dict(slot_id=r[0], name=r[1], status=r[2], count=r[3]) for r in slot_counts],
        "sources": [dict(tracking_link_id=r[0], count=r[1], name=r[2], code=r[3]) for r in sources]}


@router.get("/participants")
async def participants(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    rows = (await db.execute(select(AdvertisingEnrollment, Chat.contact_name, Chat.external_user_id)
        .join(Chat, Chat.id == AdvertisingEnrollment.chat_id).where(AdvertisingEnrollment.project_id == project_id)
        .where(AdvertisingEnrollment.scenario_id == service.scope(project_id))
        .order_by(AdvertisingEnrollment.created_at.desc(), AdvertisingEnrollment.id).limit(limit).offset(offset))).all()
    return [{**jsonable_encoder(row), "contact_name": name, "telegram_id": telegram_id} for row, name, telegram_id in rows]


@router.get("/participants/{enrollment_id}/deliveries")
async def deliveries(enrollment_id: UUID, project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    enrollment = await db.get(AdvertisingEnrollment, enrollment_id)
    if not enrollment or enrollment.project_id != project_id or enrollment.scenario_id != service.scope(project_id):
        raise HTTPException(404)
    return list((await db.scalars(select(AdvertisingDelivery).where(AdvertisingDelivery.enrollment_id == enrollment_id)
        .order_by(AdvertisingDelivery.position))).all())


@router.post("/participants/{enrollment_id}/stop")
async def stop(enrollment_id: UUID, project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    row = await db.get(AdvertisingEnrollment, enrollment_id)
    if not row or row.project_id != project_id or row.scenario_id != service.scope(project_id):
        raise HTTPException(404)
    await db.scalar(select(Chat.id).where(Chat.id == row.chat_id).with_for_update())
    await db.refresh(row)
    if row.status not in {"waiting", "active"}:
        raise HTTPException(409, "Очередь уже остановлена или завершена")
    await service.stop(row, "administrator")
    service.audit(project_id, "stopped", user.id, enrollment_id=str(row.id))
    return {"status": row.status}


@router.get("/log")
async def log(project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    return list((await db.scalars(select(AdvertisingAudit).where(AdvertisingAudit.project_id == project_id)
        .where(AdvertisingAudit.scenario_id == service.scope(project_id))
        .order_by(AdvertisingAudit.created_at.desc()).limit(100))).all())


@router.post("/backfill/preview")
async def backfill_preview(data: BackfillRequest, project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    from app.services.advertising_backfill import eligible_chats
    if data.created_before.tzinfo is None or data.created_before > now():
        raise HTTPException(422, "Граница даты должна быть в прошлом, с часовым поясом")
    cfg = await service.config(project_id)
    if not cfg.enabled:
        raise HTTPException(422, "Сначала включите рекламный сценарий")
    if data.start_slots and not data.stop_main:
        raise HTTPException(422, "Для запуска слотов необходимо остановить основную воронку")
    stmt = await eligible_chats(db, project_id, cfg, data.created_before)
    count = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    sample = list((await db.scalars(stmt.limit(20))).all())
    preview = service.audit(project_id, "backfill_preview", user.id, count=count,
        settings=cfg.model_dump(mode="json", exclude={"name"}), options=data.model_dump(mode="json", exclude={"confirmation", "preview_id"}),
        state="preview")
    await db.flush()
    return {"preview_id": preview.id, "count": count, "sample_chat_ids": sample}


@router.post("/backfill/start")
async def backfill_start(data: BackfillRequest, project_id=Depends(get_current_project_id), user=Depends(require_admin), db=Depends(get_db), service=Depends(scenario_service)):
    preview = await db.get(AdvertisingAudit, data.preview_id, with_for_update=True) if data.preview_id else None
    if not preview or preview.project_id != project_id or preview.scenario_id != service.scope(project_id) or preview.actor_id != user.id or preview.event != "backfill_preview":
        raise HTTPException(404, "Предпросмотр не найден")
    if preview.details.get("state") != "preview":
        return {"run_id": preview.id, "state": preview.details.get("state")}
    cfg = await service.config(project_id)
    if data.confirmation != "ЗАПУСТИТЬ" or preview.created_at < now() - timedelta(minutes=15) or preview.details["settings"] != cfg.model_dump(mode="json", exclude={"name"}):
        raise HTTPException(409, "Обновите предпросмотр и подтвердите запуск словом ЗАПУСТИТЬ")
    if preview.details["options"] != data.model_dump(mode="json", exclude={"confirmation", "preview_id"}):
        raise HTTPException(409, "Параметры отличаются от предпросмотра")
    preview.details = {**preview.details, "state": "queued", "processed": 0, "cursor": None}
    return {"run_id": preview.id, "state": "queued"}
