"""Exercise actual reset-chat lookup and reactivation against a local database."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateTable
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

pytest.importorskip("aiosqlite")

from app.models.chat import Chat
from app.models.base import Base
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.channel_tracking import TelegramChannelSubscriptionEvent
from app.services.channel_join_funnel_service import ChannelJoinFunnelService


async def create_lead_tables(connection):
    # Adapt PostgreSQL JSON defaults for SQLite without changing ORM metadata.
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    for model in (LeadStatus, Lead, LeadTag):
        table = metadata.tables[model.__tablename__]
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
                column.server_default = None
        await connection.execute(CreateTable(table))


@pytest.mark.parametrize("mode", ["reset", "active", "deleted"])
def test_existing_identity_never_inserts_duplicate(mode):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Chat.__table__.create)
            await create_lead_tables(connection)
            await connection.execute(text("CREATE TABLE funnel_scheduled_jobs (chat_id CHAR(32), status TEXT, updated_at DATETIME)"))
            await connection.execute(text("CREATE TABLE chat_funnel_states (chat_id CHAR(32))"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                now = datetime.now(timezone.utc)
                chat = Chat(id=uuid4(), project_id=uuid4(), bot_id=uuid4(), external_chat_id="42", external_user_id="42",
                            reset_at=now if mode == "reset" else None, is_deleted=mode == "deleted", created_at=now, updated_at=now)
                db.add(chat)
                status = LeadStatus(id=uuid4(), code="new", name="New")
                db.add(status)
                lead = Lead(id=uuid4(), project_id=chat.project_id, chat_id=chat.id,
                            status_id=status.id, is_deleted=mode == "reset", name="Old name")
                db.add(lead)
                await db.commit()
                await db.execute(text("INSERT INTO funnel_scheduled_jobs VALUES (:chat,'pending',CURRENT_TIMESTAMP)"), {"chat": chat.id.hex})
                event = TelegramChannelSubscriptionEvent(project_id=chat.project_id, tracker_bot_id=chat.bot_id,
                                                        telegram_user_id=42, first_name="Lead", tracking_link_id=None)
                found = await ChannelJoinFunnelService(db)._ensure_chat(event=event, user_chat_id=42)
                await db.commit()
                assert found.id == chat.id
                assert len((await db.scalars(select(Chat))).all()) == 1
                assert found.is_deleted == (mode == "deleted")
                assert len((await db.scalars(select(Lead))).all()) == 1
                if mode == "reset":
                    assert not lead.is_deleted
                    assert lead.name == "Lead"
                    assert await ChannelJoinFunnelService(db)._ensure_lead(event=event, chat_id=chat.id)
                    assert found.reset_at is None
                    assert found.current_cycle_started_at is not None
                    assert await db.scalar(text("SELECT status FROM funnel_scheduled_jobs")) == "cancelled"
                else:
                    assert await db.scalar(text("SELECT status FROM funnel_scheduled_jobs")) == "pending"
        finally:
            await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["active", "deleted", "trash"])
def test_existing_lead_without_reset_is_never_recreated_or_restored(mode):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await create_lead_tables(conn)
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                project_id, chat_id = uuid4(), uuid4()
                status = LeadStatus(id=uuid4(), code="new", name="New")
                db.add(status)
                lead = Lead(id=uuid4(), project_id=project_id, chat_id=chat_id, status_id=status.id,
                            name="Preserved", is_deleted=mode == "deleted", is_trash=mode == "trash")
                db.add(lead)
                await db.commit()
                event = TelegramChannelSubscriptionEvent(project_id=project_id, telegram_user_id=42)
                result = await ChannelJoinFunnelService(db)._ensure_lead(event=event, chat_id=chat_id)
                await db.commit()
                assert result is (mode == "active")
                assert len((await db.scalars(select(Lead))).all()) == 1
                assert lead.name == "Preserved"
                assert lead.is_deleted == (mode == "deleted")
                assert lead.is_trash == (mode == "trash")
        finally:
            await engine.dispose()
    asyncio.run(run())
