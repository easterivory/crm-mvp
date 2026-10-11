"""Info bot checks against disposable PostgreSQL and Redis, without mocks."""
import asyncio
import os
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.routers.info_bot import InfoBotSettings, get_info_bot, save_info_bot
from app.models import Base, Bot, Chat, Lead, Message, Project, User
from app.models.channel_tracking import TelegramChannel, TelegramChannelSubscriptionEvent
from app.models.lander import ProjectLander
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.models.tracking import TrackingLink
from app.services.info_bot_reports import InfoBotReports, period_bounds, parse_custom_period
from app.services.info_bot_service import InfoBotService, InfoBotStateStore
from app.services.tracking_metrics_service import TrackingMetricsService


def test_calendar_periods_and_moscow_bounds():
    assert period_bounds("week", today=date(2026, 10, 11)) == (date(2026, 10, 5), date(2026, 10, 11))
    assert period_bounds("week", -1, date(2026, 10, 11)) == (date(2026, 9, 28), date(2026, 10, 4))
    assert period_bounds("month", -1, date(2026, 1, 4)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert period_bounds("month", 0, date(2024, 2, 4)) == (date(2024, 2, 1), date(2024, 2, 29))
    assert parse_custom_period("01.01.2025 02.01.2025") == (date(2025, 1, 1), date(2025, 1, 2))
    with pytest.raises(ValueError):
        parse_custom_period("02.01.2025 01.01.2025")


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL") or not os.getenv("CRM_TEST_REDIS_URL"), reason="Disposable PostgreSQL and Redis required")
def test_info_bot_permissions_links_periods_and_unchanged_crm_metrics():
    async def run():
        schema = "info_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        state = InfoBotStateStore(redis_url=os.environ["CRM_TEST_REDIS_URL"])
        telegram_id = int(uuid4().hex[:10], 16)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                roles = [Role(name="super_admin"), Role(name="admin")]
                project = Project(name="Info", slug="info", tracking_lead_status_codes=["lead"])
                status = LeadStatus(name="Lead", code="lead")
                db.add_all([*roles, project, status]); await db.flush()
                super_admin = User(role=roles[0], name="Super", email="super@test.local", password_hash="unused", telegram_id=telegram_id)
                admin = User(role=roles[1], project_id=project.id, name="Admin", email="admin@test.local", password_hash="unused", telegram_id=telegram_id + 1)
                bot = Bot(project_id=project.id, name="Bot", bot_username="info_test_bot")
                db.add_all([super_admin, admin, bot]); await db.flush()
                channel = TelegramChannel(project_id=project.id, tracker_bot_id=bot.id, title="Channel", telegram_chat_id=-100123)
                db.add(channel); await db.flush()
                link = TrackingLink(project_id=project.id, bot_id=bot.id, name="Link", title="Link", code="infotest", ref_code="infotest", invite_link="https://t.me/+invite_test")
                db.add(link); await db.flush()
                chat = Chat(project_id=project.id, bot_id=bot.id, tracking_link_id=link.id, external_chat_id="12345", external_user_id="12345")
                db.add(chat); await db.flush()
                occurred = datetime(2025, 1, 5, 22, 0, tzinfo=timezone.utc)  # Monday 01:00 MSK.
                db.add_all([
                    Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, created_at=occurred),
                    Message(chat_id=chat.id, tracking_link_id=link.id, sender_type="user", body="/start infotest", created_at=occurred),
                    ProjectLander(project_id=project.id, name="Landing", slug="info-landing", type="default_tg_redirect", tracking_link_id=link.id),
                    TelegramChannelSubscriptionEvent(project_id=project.id, channel_id=channel.id, tracker_bot_id=bot.id,
                        tracking_link_id=link.id, telegram_user_id=12345, telegram_update_id=1, event_type="join", occurred_at=occurred),
                ])
                await db.commit()
                service = InfoBotService(db, state)
                assert await service.authorized_user(telegram_id)
                assert await service.authorized_user(telegram_id + 1) is None
                with pytest.raises(HTTPException) as exc:
                    await get_info_bot(admin, db)
                assert exc.value.status_code == 403
                assert (await get_info_bot(super_admin, db))["enabled"] is False
                assert (await save_info_bot(InfoBotSettings(enabled=False), super_admin, db))["has_token"] is False
                with pytest.raises(HTTPException):
                    await save_info_bot(InfoBotSettings(enabled=True), super_admin, db)
                for value in ("https://telegram.me/info_test_bot?start=infotest", "https://t.me/info_test_bot?start=infotest",
                              "https://example.test/join/infotest", "https://example.test/l/info-landing", "https://t.me/+invite_test", "https://telegram.me/+invite_test"):
                    assert (await service.resolve_link(value)).id == link.id
                assert await service.resolve_link("https://t.me/wrong_bot?start=infotest") is None
                monday = date(2025, 1, 6)
                info = await InfoBotReports(db).summary(project, monday, monday, link)
                assert info["leads"] == info["channel_joins"] == info["starts"] == 1
                crm = await TrackingMetricsService(db).get_link_metrics(super_admin, link.id, monday, monday)
                assert crm.summary.leads == crm.summary.channel_joins == crm.summary.starts == 0
                def update(sender, chat_type="private", message="/stats"):
                    return {"message": {"from": {"id": sender}, "chat": {"id": sender, "type": chat_type}, "text": message}}
                _, replies = await service.handle_update(update(telegram_id + 1))
                assert "Доступ только" in replies[0]["text"]
                assert await service.handle_update(update(telegram_id, "group")) == (None, [])
                _, replies = await service.handle_update(update(telegram_id))
                assert replies[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"project:{project.id}"
                replies = await service.callback(telegram_id, f"project:{project.id}", {})
                assert "Info" in replies[0]["text"]
                stored = await state.get(telegram_id)
                replies = await service.callback(telegram_id, "period:all:0", stored)
                assert "Лиды: 1" in replies[0]["text"] and "Подписчики канала: 1" in replies[0]["text"]
                _, replies = await service.handle_update(update(telegram_id, message="https://telegram.me/info_test_bot?start=infotest https://t.me/info_test_bot?start=infotest"))
                assert len(replies) == 2 and "Всё время" in replies[1]["text"]
                stored = await state.get(telegram_id)
                assert len(stored["link_ids"]) == 1
                await service.callback(telegram_id, "custom", stored)
                _, replies = await service.handle_update(update(telegram_id, message="06.01.2025 06.01.2025"))
                assert "Подписчики канала: 1" in replies[0]["text"] and "Лиды: 1" in replies[0]["text"]
                super_admin.role = roles[1]
                await db.flush()
                _, replies = await service.handle_update(update(telegram_id))
                assert "Доступ только" in replies[0]["text"] and await state.get(telegram_id) is None
        finally:
            await state.clear(telegram_id)
            await state.clear(telegram_id + 1)
            await state.close()
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
