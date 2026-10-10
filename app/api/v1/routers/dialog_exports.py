import hashlib
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.arq_queues import DIALOG_EXPORT_QUEUE_NAME
from app.core.config import settings
from app.core.redis import get_redis
from app.models.user import User
from app.schemas.dialog_export import DialogExportRequest, DialogExportStatus
from app.services.dialog_export_files import EXPORT_TTL, resolve_export
from app.services.dialog_export_service import ensure_export_access, ensure_export_user_access, load_metadata, release_lock, save_metadata

router = APIRouter()


@router.post('/exports', response_model=DialogExportStatus, status_code=202)
async def create_export(body: DialogExportRequest, project_id: UUID = Depends(get_current_project_id),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_export_access(db, user, project_id, body.bot_id)
    user_id = str(user.id)
    await db.rollback()  # Release the read transaction before communicating with Redis.
    redis = await get_redis()
    if not await redis.exists(f'{DIALOG_EXPORT_QUEUE_NAME}:health-check'):
        raise HTTPException(503, 'Воркер экспорта недоступен. Администратору нужно запустить сервис exports.')
    export_id = str(uuid4())
    if not await redis.set(f'dialog-export:lock:{project_id}', export_id, nx=True, ex=EXPORT_TTL):
        raise HTTPException(409, 'В проекте уже собирается выгрузка. Дождитесь её завершения.')
    data = dict(id=export_id, project_id=str(project_id), user_id=user_id, status='queued',
                created_at=datetime.now(timezone.utc).isoformat(), request=body.model_dump(mode='json'))
    pool = None
    try:
        await save_metadata(redis, data)
        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        job = await pool.enqueue_job('run_dialog_export', export_id, _queue_name=DIALOG_EXPORT_QUEUE_NAME,
                                     _job_id=f'dialog-export-{export_id}')
        if job is None:
            raise RuntimeError('Export job was not enqueued')
    except Exception:
        await release_lock(redis, data)
        data.update(status='failed', error='Очередь экспорта недоступна. Повторите позже.')
        await save_metadata(redis, data)
        raise HTTPException(503, data['error']) from None
    finally:
        if pool:
            await pool.aclose()
    return data


@router.get('/exports/{export_id}', response_model=DialogExportStatus)
async def export_status(export_id: UUID, project_id: UUID = Depends(get_current_project_id),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_export_access(db, user, project_id)
    return await load_metadata(await get_redis(), export_id, project_id)


@router.delete('/exports/{export_id}', response_model=DialogExportStatus)
async def cancel_export(export_id: UUID, project_id: UUID = Depends(get_current_project_id),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_export_access(db, user, project_id)
    redis = await get_redis()
    data = await load_metadata(redis, export_id, project_id)
    if data['status'] in {'queued', 'running', 'cancelling'}:
        await redis.set(f'dialog-export:cancel:{export_id}', '1', ex=EXPORT_TTL)
        # Do not overwrite worker progress/terminal status: the cancellation key is authoritative.
        data['status'] = 'cancelling'
    return data


@router.post('/exports/{export_id}/download')
async def export_download(export_id: UUID, project_id: UUID = Depends(get_current_project_id),
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_export_access(db, user, project_id)
    redis = await get_redis()
    data = await load_metadata(redis, export_id, project_id)
    if data['status'] != 'ready':
        raise HTTPException(409, 'Выгрузка ещё не готова')
    try:
        resolve_export(project_id, export_id)
    except FileNotFoundError:
        raise HTTPException(410, 'Выгрузка истекла. Создайте новую.') from None
    ticket = secrets.token_urlsafe(32)
    await redis.set('dialog-export:ticket:' + hashlib.sha256(ticket.encode()).hexdigest(),
                    json.dumps(dict(export_id=str(export_id), project_id=str(project_id), user_id=str(user.id))), ex=60)
    return {'url': f'/chats/exports/{export_id}/file?ticket={ticket}'}


@router.get('/exports/{export_id}/file')
async def export_file(export_id: UUID, ticket: str = Query(min_length=32, max_length=128),
                      db: AsyncSession = Depends(get_db)):
    redis = await get_redis()
    value = await redis.getdel('dialog-export:ticket:' + hashlib.sha256(ticket.encode()).hexdigest())
    if not value:
        raise HTTPException(403, 'Ссылка скачивания истекла или уже использована')
    scope = json.loads(value)
    if scope['export_id'] != str(export_id):
        raise HTTPException(403, 'Неверная ссылка скачивания')
    project_id = UUID(scope['project_id'])
    await ensure_export_user_access(db, UUID(scope['user_id']), project_id)
    data = await load_metadata(redis, export_id, project_id)
    if data['status'] != 'ready':
        raise HTTPException(409, 'Выгрузка не готова')
    try:
        path = resolve_export(project_id, export_id)
    except FileNotFoundError:
        raise HTTPException(410, 'Выгрузка истекла. Создайте новую.') from None
    await db.rollback()
    return FileResponse(path, media_type='application/zip', filename=f'dialogs_{export_id}.zip',
                        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
