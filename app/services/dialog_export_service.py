"""Read-only, paginated dialog export. No transport credentials are serialized."""
import asyncio
import json
import logging
from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, tuple_

from app.core.constants import RoleName
from app.core.database import get_db_session
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState, Funnel, FunnelStep
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.project import Project
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.repositories.user_repository import UserRepository
from app.schemas.dialog_export import DialogExportRequest
from app.services.access_control import require_project_access
from app.services.dialog_export_files import DialogArchive, EXPORT_TTL, ExportLimitError

logger = logging.getLogger(__name__)


def metadata_key(export_id):
    return f"dialog-export:{export_id}"


async def save_metadata(redis, data):
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    await redis.set(metadata_key(data['id']), json.dumps(data), ex=EXPORT_TTL)


async def load_metadata(redis, export_id, project_id=None):
    value = await redis.get(metadata_key(export_id))
    if not value:
        raise HTTPException(404, "Выгрузка не найдена или срок хранения истёк")
    data = json.loads(value)
    if project_id is not None and data['project_id'] != str(project_id):
        raise HTTPException(404, "Выгрузка не найдена")
    if data['status'] == 'running' and datetime.now(timezone.utc) - datetime.fromisoformat(data.get('updated_at', data['created_at'])) > timedelta(minutes=10):
        data.update(status='failed', error='Воркер экспорта перестал отвечать. Создайте новую выгрузку.')
        await save_metadata(redis, data)
        await release_lock(redis, data)
    return data


async def ensure_export_access(db, user, project_id, bot_id=None):
    if user is None or user.is_deleted or user.role_name not in {RoleName.ADMIN, RoleName.SUPER_ADMIN}:
        raise HTTPException(403, "Экспорт доступен только администраторам")
    require_project_access(user, project_id)
    if not await db.scalar(select(Project.id).where(Project.id == project_id, Project.is_deleted.is_(False))):
        raise HTTPException(404, "Проект не найден")
    if bot_id and not await db.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.project_id == project_id, Bot.is_deleted.is_(False))):
        raise HTTPException(404, "Бот не найден")


async def release_lock(redis, data):
    await redis.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", 1,
                     f"dialog-export:lock:{data['project_id']}", data['id'])


async def ensure_export_user_access(db, user_id, project_id):
    user = await UserRepository(db).get_by_id(user_id)
    await ensure_export_access(db, user, project_id)


def button_labels(markup):
    if not isinstance(markup, dict):
        return []
    rows = markup.get('inline_keyboard') or markup.get('keyboard') or []
    if not isinstance(rows, list):
        return []
    return [button['text'] for row in rows if isinstance(row, list) for button in row
            if isinstance(button, dict) and isinstance(button.get('text'), str)]


class ExportCancelled(Exception):
    pass


async def archive_io(function, *args):
    # Cancellation must not close a ZIP while its compression thread is still writing.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


async def build_export(redis, data, session_factory=get_db_session):
    request = DialogExportRequest.model_validate(data['request'])
    project_id = UUID(data['project_id'])
    cutoff = datetime.fromisoformat(data['created_at'])
    message_filters = [Message.created_at <= cutoff]
    if request.date_from:
        message_filters.append(Message.created_at >= datetime.combine(request.date_from, time.min, timezone.utc))
    if request.date_to:
        message_filters.append(Message.created_at < datetime.combine(request.date_to + timedelta(days=1), time.min, timezone.utc))
    chat_filters = [Chat.project_id == project_id, Chat.is_deleted.is_(False), Chat.reset_at.is_(None), Chat.created_at <= cutoff]
    if request.bot_id:
        chat_filters.append(Chat.bot_id == request.bot_id)
    if request.date_from or request.date_to:
        chat_filters.append(select(Message.id).where(Message.chat_id == Chat.id, *message_filters).exists())
    manifest = {'schema_version': 1, 'project_id': str(project_id), 'created_at': data['created_at'],
                'request': data['request'], 'notes': ['Текст сообщений может содержать персональные данные.',
                'Вложения: только метаданные, без файлов. Изменения во время экспорта не образуют снимок базы.']}
    archive = await asyncio.to_thread(DialogArchive, project_id, UUID(data['id']), manifest)
    chats = messages = 0
    cursor = None
    try:
        while True:
            if await redis.exists(f"dialog-export:cancel:{data['id']}"):
                raise ExportCancelled()
            query = select(Chat.id, Chat.bot_id, Chat.created_at, Chat.external_user_id, Chat.contact_name,
                           Bot.name.label('bot_name'), Lead.id.label('lead_id'), Lead.name, Lead.phone,
                           Lead.username, Lead.country, Lead.manager_comment, Lead.score_percent,
                           LeadStatus.name.label('status'), Funnel.name.label('funnel_name'),
                           FunnelStep.title.label('current_step'), ChatFunnelState.completed_at,
                           TrackingLink.name.label('tracking_link_name'), Chat.tracking_link_id).outerjoin(Bot, Bot.id == Chat.bot_id).outerjoin(
                               Lead, (Lead.chat_id == Chat.id) & Lead.is_deleted.is_(False)).outerjoin(
                                   LeadStatus, LeadStatus.id == Lead.status_id).outerjoin(
                                       ChatFunnelState, ChatFunnelState.chat_id == Chat.id).outerjoin(
                                           Funnel, Funnel.id == ChatFunnelState.funnel_id).outerjoin(
                                               FunnelStep, FunnelStep.id == ChatFunnelState.current_step_id).outerjoin(
                                                   TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(*chat_filters).order_by(Chat.id).limit(50)
            if cursor:
                query = query.where(Chat.id > cursor)
            async with session_factory() as db:
                rows = (await db.execute(query)).mappings().all()
                lead_ids = [r['lead_id'] for r in rows if r['lead_id']]
                tags = (await db.execute(select(LeadTag.lead_id, Tag.name).join(Tag, Tag.id == LeadTag.tag_id).where(
                    LeadTag.lead_id.in_(lead_ids), Tag.project_id == project_id).order_by(Tag.name))).all() if lead_ids else []
            if not rows:
                break
            tag_map = {}
            for lead_id, name in tags:
                tag_map.setdefault(lead_id, []).append(name)
            for row in rows:
                if await redis.exists(f"dialog-export:cancel:{data['id']}"):
                    raise ExportCancelled()
                chat_id = row['id']
                context = {'type': 'chat', 'id': str(chat_id), 'bot_id': str(row['bot_id']) if row['bot_id'] else None,
                           'bot_name': row['bot_name'], 'created_at': str(row['created_at']), 'status': row['status'],
                           'country': row['country'], 'score_percent': row['score_percent'], 'tags': tag_map.get(row['lead_id'], [])}
                context.update(funnel_name=row['funnel_name'], current_step=row['current_step'],
                               funnel_completed_at=str(row['completed_at']) if row['completed_at'] else None,
                               tracking_link_name=row['tracking_link_name'],
                               tracking_link_id=str(row['tracking_link_id']) if row['tracking_link_id'] else None)
                if request.include_contacts:
                    context['contacts'] = {key: str(row[key]) if row[key] is not None else None for key in
                                           ('external_user_id', 'contact_name', 'name', 'phone', 'username', 'manager_comment')}
                await archive_io(archive.write_records, [context])
                msg_cursor = None
                while True:
                    if await redis.exists(f"dialog-export:cancel:{data['id']}"):
                        raise ExportCancelled()
                    query = select(Message.id, Message.created_at, Message.sender_type, Message.message_type,
                        Message.body, Message.caption, Message.original_text, Message.translated_text,
                        Message.file_name, Message.mime_type, Message.file_size, Message.media_group_id,
                        Message.reply_to_message_id, Message.edited_at, Message.deleted_at,
                        Message.sender_id, Message.operator_id,
                        Message.raw_payload_json['reply_markup'].label('markup'),
                        Message.raw_payload_json['telegram_result']['reply_markup'].label('result_markup')).where(
                            Message.chat_id == chat_id, *message_filters).order_by(Message.created_at, Message.id).limit(500)
                    if msg_cursor:
                        query = query.where(tuple_(Message.created_at, Message.id) > msg_cursor)
                    async with session_factory() as db:
                        batch = (await db.execute(query)).mappings().all()
                    if not batch:
                        break
                    records = []
                    for msg in batch:
                        record = {key: str(value) if isinstance(value, (UUID, datetime)) else value for key, value in msg.items()
                                  if key not in {'body', 'caption', 'file_name', 'mime_type', 'file_size', 'markup', 'result_markup'}}
                        record.update(type='message', chat_id=str(chat_id), text=msg['body'] or msg['caption'] or '')
                        record['buttons'] = button_labels(msg['markup']) or button_labels(msg['result_markup'])
                        author_id = msg['operator_id'] or msg['sender_id']
                        record['author'] = f"{msg['sender_type']}:{author_id}" if author_id else msg['sender_type']
                        if msg['message_type'] not in {'text', 'system'}:
                            record['attachment'] = {key: msg[key] for key in ('file_name', 'mime_type', 'file_size', 'media_group_id')}
                        records.append(record)
                    await archive_io(archive.write_records, records)
                    messages += len(batch)
                    msg_cursor = (batch[-1]['created_at'], batch[-1]['id'])
                    data.update(chats=chats, messages=messages)
                    await save_metadata(redis, data)
                chats += 1
            cursor = rows[-1]['id']
            data.update(chats=chats, messages=messages)
            await save_metadata(redis, data)
        if await redis.exists(f"dialog-export:cancel:{data['id']}"):
            raise ExportCancelled()
        path = await archive_io(archive.finish, {'chats': chats, 'messages': messages})
        return path, chats, messages
    except BaseException:
        await asyncio.to_thread(archive.abort)
        raise


async def run_dialog_export(ctx, export_id):
    redis = ctx['redis']
    data = await load_metadata(redis, export_id)
    if data['status'] != 'queued':
        return
    try:
        async with get_db_session() as db:
            user = await UserRepository(db).get_by_id(UUID(data['user_id']))
            await ensure_export_access(db, user, UUID(data['project_id']), UUID(data['request']['bot_id']) if data['request']['bot_id'] else None)
        data['status'] = 'running'
        await save_metadata(redis, data)
        path, chats, messages = await build_export(redis, data)
        data.update(status='ready', chats=chats, messages=messages, size_bytes=path.stat().st_size)
        logger.info('Dialog export ready export_id=%s project_id=%s chats=%s messages=%s bytes=%s',
                    export_id, data['project_id'], chats, messages, data['size_bytes'])
    except (ExportCancelled, asyncio.CancelledError):
        data['status'] = 'cancelled'
    except Exception as exc:
        logger.exception('Dialog export failed export_id=%s project_id=%s', export_id, data['project_id'])
        data.update(status='failed', error=str(exc) if isinstance(exc, ExportLimitError) else 'Не удалось создать выгрузку. Проверьте серверные логи.')
    finally:
        await save_metadata(redis, data)
        await release_lock(redis, data)
