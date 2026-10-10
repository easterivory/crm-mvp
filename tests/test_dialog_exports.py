"""Exports against real PostgreSQL/Redis and filesystem, without mocks."""
import asyncio
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models import Base, Bot, Chat, Lead, Message, Project, User
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.schemas.dialog_export import DialogExportRequest
from app.services.dialog_export_files import DialogArchive, ExportLimitError
from app.services.dialog_export_service import (
    ExportCancelled, build_export, ensure_export_access, load_metadata, release_lock, save_metadata,
)


def test_export_validates_dates_format_and_default_privacy():
    assert DialogExportRequest().include_contacts is False
    with pytest.raises(ValueError):
        DialogExportRequest(date_from='2026-10-10', date_to='2026-10-09')
    with pytest.raises(ValueError):
        DialogExportRequest(format='html')


def test_archive_split_limits_cleanup_and_transcript(tmp_path):
    original = settings.CHAT_ATTACHMENT_STORAGE_PATH
    settings.CHAT_ATTACHMENT_STORAGE_PATH = str(tmp_path)
    try:
        manifest = {'request': {'format': 'jsonl'}}
        archive = DialogArchive(uuid4(), uuid4(), manifest)
        archive.part_limit = 300
        archive.write_records([{'type': 'chat', 'id': 'one'}, *[{'type': 'message', 'created_at': 'today',
            'id': str(i), 'sender_type': 'user', 'text': 'hello ' * 20} for i in range(5)]])
        path = archive.finish({'chats': 1, 'messages': 5})
        with zipfile.ZipFile(path) as contents:
            meta = json.loads(contents.read('manifest.json'))
            assert len(meta['parts']) > 1
            records = [json.loads(line) for part in meta['parts'] for line in contents.read(part).decode().splitlines()]
            assert len([r for r in records if r['type'] == 'message']) == 5
        archive = DialogArchive(uuid4(), uuid4(), {'request': {'format': 'txt'}})
        archive.write_records([{'type': 'chat', 'id': 'one'}, {'type': 'message', 'id': 'two', 'created_at': 'today',
            'sender_type': 'user', 'text': 'Здравствуйте', 'deleted_at': 'today', 'attachment': {'mime_type': 'image/png'}}])
        path = archive.finish({'chats': 1, 'messages': 1})
        with zipfile.ZipFile(path) as contents:
            transcript = contents.read('dialogs_0001.txt').decode()
            assert 'Здравствуйте' in transcript and '[удалено]' in transcript and 'image/png' in transcript
        archive = DialogArchive(uuid4(), uuid4(), manifest)
        archive.limit = 1
        with pytest.raises(ExportLimitError):
            archive.write_records([{'type': 'chat', 'id': 'one'}])
        archive.abort()
        assert not archive.path.exists()
    finally:
        settings.CHAT_ATTACHMENT_STORAGE_PATH = original


@pytest.mark.skipif(not os.getenv('CRM_TEST_POSTGRES_URL') or not os.getenv('CRM_TEST_REDIS_URL'), reason='Disposable PostgreSQL and Redis required')
def test_real_export_pagination_scope_dates_privacy_and_read_only(tmp_path):
    async def run():
        schema = 'exports_' + uuid4().hex
        root = create_async_engine(os.environ['CRM_TEST_POSTGRES_URL'])
        engine = create_async_engine(os.environ['CRM_TEST_POSTGRES_URL'], connect_args={'server_settings': {'search_path': schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(os.environ['CRM_TEST_REDIS_URL'])
        original = settings.CHAT_ATTACHMENT_STORAGE_PATH
        settings.CHAT_ATTACHMENT_STORAGE_PATH = str(tmp_path)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name='Exports', slug='exports')
                other = Project(name='Other', slug='other')
                role = Role(name='admin')
                manager_role = Role(name='manager')
                status = LeadStatus(name='New', code='new')
                db.add_all([project, other, role, manager_role, status]); await db.flush()
                admin = User(project_id=project.id, role=role, name='Admin', email='admin@test.local', password_hash='private-password')
                manager = User(project_id=project.id, role=manager_role, name='Manager', email='manager@test.local', password_hash='private-password')
                bots = [Bot(project_id=p.id, name=f'Bot {i}', telegram_token='must-never-export') for i, p in enumerate([project, project, other])]
                db.add_all([admin, manager, *bots]); await db.flush()
                now = datetime.now(timezone.utc)
                chats = [Chat(project_id=p.id, bot_id=b.id, external_chat_id=str(i), external_user_id=str(i),
                    contact_name='private-name', created_at=now - timedelta(days=3), is_read=False) for i, (p, b) in enumerate(zip([project, project, other], bots))]
                db.add_all(chats); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chats[0].id, status_id=status.id, phone='private-phone', manager_comment='private-comment')
                db.add(lead)
                db.add_all([Message(chat_id=chats[0].id, sender_type='user', body=f'answer-{i}', created_at=now - timedelta(days=1),
                    raw_payload_json={'token': 'must-never-export', 'reply_markup': {'inline_keyboard': [[
                        {'text': 'Answer button', 'callback_data': 'must-never-export'}]]}}) for i in range(1003)])
                db.add_all([Message(chat_id=chats[0].id, sender_type='user', body='old-outside-period', created_at=now - timedelta(days=2)),
                    Message(chat_id=chats[1].id, sender_type='bot', body='second-bot', created_at=now - timedelta(days=1)),
                    Message(chat_id=chats[2].id, sender_type='user', body='other-project-secret', created_at=now - timedelta(days=1))])
                await db.commit()
                await ensure_export_access(db, admin, project.id, bots[0].id)
                for user, pid, bid in [(manager, project.id, None), (admin, other.id, None), (admin, project.id, bots[2].id)]:
                    with pytest.raises(HTTPException):
                        await ensure_export_access(db, user, pid, bid)
                data = {'id': str(uuid4()), 'project_id': str(project.id), 'user_id': str(admin.id), 'status': 'running',
                    'created_at': now.isoformat(), 'request': DialogExportRequest(bot_id=bots[0].id, format='jsonl',
                        date_from=(now - timedelta(days=1)).date(), date_to=(now - timedelta(days=1)).date()).model_dump(mode='json')}
                path, count, total = await build_export(redis, data, sessions)
                assert (count, total) == (1, 1003)
                with zipfile.ZipFile(path) as content:
                    payload = content.read('dialogs_0001.jsonl').decode()
                    assert all(secret not in payload for secret in ['private-name', 'private-phone', 'must-never-export', 'other-project-secret', 'second-bot', 'old-outside-period'])
                    messages = [json.loads(line) for line in payload.splitlines() if json.loads(line)['type'] == 'message']
                    assert len({msg['id'] for msg in messages}) == 1003
                    assert messages[0]['buttons'] == ['Answer button']
                data['id'] = str(uuid4())
                data['request'] = DialogExportRequest(format='txt', include_contacts=True).model_dump(mode='json')
                path, count, total = await build_export(redis, data, sessions)
                assert (count, total) == (2, 1005)
                with zipfile.ZipFile(path) as content:
                    payload = content.read('dialogs_0001.txt').decode()
                    assert 'private-phone' in payload and 'second-bot' in payload and 'other-project-secret' not in payload
                await db.refresh(chats[0])
                assert chats[0].is_read is False and chats[0].last_read_at is None and chats[0].assignment_expires_at is None
                data['id'] = str(uuid4())
                await redis.set(f"dialog-export:cancel:{data['id']}", '1', ex=60)
                with pytest.raises(ExportCancelled):
                    await build_export(redis, data, sessions)
                assert not list(tmp_path.glob('dialog_exports/*/*.partial'))
                await save_metadata(redis, data)
                with pytest.raises(HTTPException):
                    await load_metadata(redis, data['id'], other.id)
                key = f'dialog-export:lock:{project.id}'
                await redis.set(key, 'someone-else', ex=60)
                await release_lock(redis, data)
                assert await redis.get(key) == b'someone-else'
                await redis.delete(key)
                data.update(status='running', updated_at=(now - timedelta(minutes=20)).isoformat())
                await redis.set(key, data['id'], ex=60)
                await redis.set('dialog-export:' + data['id'], json.dumps(data), ex=60)
                failed = await load_metadata(redis, data['id'], project.id)
                assert failed['status'] == 'failed'
                assert await redis.get(key) is None
        finally:
            settings.CHAT_ATTACHMENT_STORAGE_PATH = original
            await redis.aclose()
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
