"""Real photo, multipart, PostgreSQL permissions and cancellation race checks."""
import asyncio
import importlib.util
import io
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.constants import RoleName
from app.models import Base, Chat, Project, User
from app.models.role import Role
from app.models.scheduled_message import ScheduledMessage
from app.repositories.scheduled_message_repository import ScheduledMessageRepository
from app.services.chat_photo_album import AlbumPhoto, photo_album_form, prepare_album, validate_album
from app.services.scheduled_message_service import ScheduledMessageService


def photo(format="PNG", name="photo.png"):
    output = io.BytesIO()
    Image.new("RGB", (100, 60), (50, 160, 210)).save(output, format=format)
    return AlbumPhoto(output.getvalue(), name, "image/" + format.lower())


def test_album_validation_and_transport_safe_file_names():
    photos = prepare_album([photo(name="../../wrong.txt"), photo("WEBP", "second.webp")])
    assert [item.file_name for item in photos] == ["wrong.png", "second.jpg"]
    assert [item.mime_type for item in photos] == ["image/png", "image/jpeg"]
    with Image.open(io.BytesIO(photos[1].content)) as image:
        assert image.format == "JPEG"
    for invalid in ([photo()], [photo()] * 11, [photo(), AlbumPhoto(b"not a photo", "bad.png", "image/png")],
                    [photo(), photo("GIF", "animated.gif")]):
        with pytest.raises(HTTPException):
            validate_album(invalid)


def test_real_multipart_album_has_one_caption_and_reply():
    photos = prepare_album([photo(), photo()])
    data, files = photo_album_form(photos, "123", "Общая подпись", {"message_id": 42})
    media = json.loads(data["media"])
    assert media[0]["caption"] == "Общая подпись"
    assert "caption" not in media[1]
    assert {item["media"].removeprefix("attach://") for item in media} == set(files)
    assert json.loads(data["reply_parameters"]) == {"message_id": 42}
    request = httpx.Request("POST", "https://api.telegram.org/", data=data, files=files)
    body = request.read()
    assert "multipart/form-data" in request.headers["Content-Type"]
    assert b'name="photo_0"' in body and b'name="photo_1"' in body
    assert all(item.content in body for item in photos)


@asynccontextmanager
async def database():
    schema = "albums_" + uuid4().hex
    root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
    engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    try:
        async with root.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        async with root.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await root.dispose()


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_managers_can_cancel_colleagues_messages_and_albums_only_in_their_project(tmp_path):
    async def run():
        async with database() as engine:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as db:
                project = Project(name="Albums", slug="albums")
                other = Project(name="Other", slug="other")
                manager_role = Role(name=RoleName.MANAGER)
                buyer_role = Role(name=RoleName.BUYER)
                db.add_all([project, other, manager_role, buyer_role])
                await db.flush()
                creator = User(project_id=project.id, role=manager_role, name="Creator", email="creator@example.test", password_hash="not-used")
                colleague = User(project_id=project.id, role=manager_role, name="Colleague", email="colleague@example.test", password_hash="not-used")
                outsider = User(project_id=other.id, role=manager_role, name="Outsider", email="outsider@example.test", password_hash="not-used")
                buyer = User(project_id=project.id, role=buyer_role, name="Buyer", email="buyer@example.test", password_hash="not-used")
                chat = Chat(project_id=project.id, external_chat_id="123", external_user_id="123")
                db.add_all([creator, colleague, outsider, buyer, chat])
                await db.commit()
                service = ScheduledMessageService(db)
                scheduled = await service.schedule_message(project_id=project.id, chat_id=chat.id, actor=creator,
                    scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1), text="Original text",
                    original_text=None, media_type="text", auto_translate=False)
                await db.commit()
                for actor in (outsider, buyer):
                    with pytest.raises(HTTPException) as denied:
                        await service.cancel_message(project_id=project.id, chat_id=chat.id, scheduled_message_id=scheduled.id, actor=actor)
                    assert denied.value.status_code == 403
                with pytest.raises(HTTPException) as wrong_chat:
                    await service.cancel_message(project_id=project.id, chat_id=uuid4(), scheduled_message_id=scheduled.id, actor=colleague)
                assert wrong_chat.value.status_code == 404
                await service.cancel_message(project_id=project.id, chat_id=chat.id, scheduled_message_id=scheduled.id, actor=colleague)
                item = await db.get(ScheduledMessage, scheduled.id, populate_existing=True)
                assert item.status == "cancelled" and item.created_by_user_id == creator.id
                assert item.text == "Original text"
                with pytest.raises(HTTPException) as repeated:
                    await service.cancel_message(project_id=project.id, chat_id=chat.id, scheduled_message_id=scheduled.id, actor=colleague)
                assert repeated.value.status_code == 422
                old_path = settings.CHAT_ATTACHMENT_STORAGE_PATH
                settings.CHAT_ATTACHMENT_STORAGE_PATH = str(tmp_path)
                try:
                    album = await service.schedule_message(project_id=project.id, chat_id=chat.id, actor=creator,
                        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1), text="Album caption",
                        original_text=None, media_type="photo", auto_translate=False, album_photos=[photo(), photo()])
                    await db.commit()
                    item = await db.get(ScheduledMessage, album.id)
                    paths = [Path(entry["storage_path"]) for entry in item.album_files]
                    assert album.album_count == 2 and all(path.is_file() for path in paths)
                    assert "storage_path" not in album.model_dump()
                    await service.cancel_message(project_id=project.id, chat_id=chat.id, scheduled_message_id=album.id, actor=colleague)
                    assert not any(path.exists() for path in paths)
                finally:
                    settings.CHAT_ATTACHMENT_STORAGE_PATH = old_path
                await db.execute(update(ScheduledMessage).where(ScheduledMessage.status == "cancelled").values(
                    scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
                await db.commit()
                assert await service.process_due_messages() == 0

                race = ScheduledMessage(project_id=project.id, chat_id=chat.id, created_by_user_id=creator.id,
                                        scheduled_at=datetime.now(timezone.utc), text="Race")
                db.add(race)
                await db.commit()
                async def compete(cancel):
                    async with factory() as session:
                        repo = ScheduledMessageRepository(session)
                        won = await repo.cancel(race.id, project.id) if cancel else await repo.mark_running(race.id)
                        await session.commit()
                        return won
                wins = await asyncio.gather(compete(True), compete(False))
                assert sorted(wins) == [False, True]
                result = await db.get(ScheduledMessage, race.id, populate_existing=True)
                assert result.status == ("cancelled" if wins[0] else "running")
                if result.status == "running":
                    with pytest.raises(HTTPException) as running:
                        await service.cancel_message(project_id=project.id, chat_id=chat.id, scheduled_message_id=race.id, actor=colleague)
                    assert running.value.status_code == 422
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_album_migration_upgrade_downgrade_preserves_existing_scheduled_messages():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261010_0081_scheduled_photo_albums.py"
    spec = importlib.util.spec_from_file_location("album_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async def run():
        async with database() as engine:
            async with engine.begin() as connection:
                await connection.execute(text("ALTER TABLE scheduled_messages DROP COLUMN album_files"))
                await connection.execute(text("INSERT INTO projects(id,name,slug) VALUES ('11111111-1111-1111-1111-111111111111','Migration','migration')"))
                await connection.execute(text("INSERT INTO roles(id,name) VALUES ('22222222-2222-2222-2222-222222222222','manager')"))
                await connection.execute(text("INSERT INTO users(id,project_id,role_id,name,email,password_hash) VALUES ('33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222','Manager','migration@example.test','not-used')"))
                await connection.execute(text("INSERT INTO chats(id,project_id,external_chat_id,external_user_id) VALUES ('44444444-4444-4444-4444-444444444444','11111111-1111-1111-1111-111111111111','123','123')"))
                await connection.execute(text("INSERT INTO scheduled_messages(id,project_id,chat_id,created_by_user_id,scheduled_at,text) VALUES ('55555555-5555-5555-5555-555555555555','11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','33333333-3333-3333-3333-333333333333',now(),'Legacy text')"))
                def apply(sync, function):
                    with Operations.context(MigrationContext.configure(sync)):
                        function()
                await connection.run_sync(apply, migration.upgrade)
                assert (await connection.execute(text("SELECT text,album_files FROM scheduled_messages"))).one() == ("Legacy text", None)
                await connection.run_sync(apply, migration.downgrade)
                assert (await connection.execute(text("SELECT text FROM scheduled_messages"))).scalar_one() == "Legacy text"
                await connection.run_sync(apply, migration.upgrade)
    asyncio.run(run())
