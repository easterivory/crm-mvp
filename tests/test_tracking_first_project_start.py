"""First-start statistics against real PostgreSQL; no substituted repositories."""
import asyncio
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.constants import SenderType, TrackingCostModel
from app.models import Base, Bot, Chat, Message, Project, Role, TrackingLink, User
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.repositories.tracking_repository import TrackingLinkRepository
from app.repositories.tracking_start_query import is_first_project_start


def test_first_start_query_searches_history_before_report_filters():
    query = select(Message.id).join(Chat, Chat.id == Message.chat_id).where(
        is_first_project_start(), Chat.bot_id == uuid4(),
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "NOT (EXISTS" in sql
    assert "earlier_start_chat.project_id = chats.project_id" in sql
    assert "earlier_start_chat.external_user_id = chats.external_user_id" in sql
    assert "earlier_start_message.created_at, earlier_start_message.id" in sql
    assert "earlier_start_chat.bot_id" not in sql
    assert "earlier_start_chat.is_deleted" not in sql


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_first_start_counts_agree_across_bots_links_dates_and_graphs():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "first_starts_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                projects = [Project(name="First starts", slug="first"), Project(name="Separate", slug="separate")]
                db.add_all(projects)
                await db.flush()
                project, other = projects
                bots = [Bot(project_id=project.id, name="A"), Bot(project_id=project.id, name="B"),
                        Bot(project_id=other.id, name="Other")]
                db.add_all(bots)
                await db.flush()
                a, b, other_bot = bots
                links = [TrackingLink(project_id=project.id, bot_id=bot.id, name=key, title=key,
                                     code=key, ref_code=key, cost_model=TrackingCostModel.FIX_PDP,
                                     price_per_unit=Decimal("1"))
                         for key, bot in [("first-a", a), ("second-b", b), ("repeat-a", a)]]
                db.add_all(links)
                await db.flush()
                first_link, second_link, repeat_link = links
                chats = {}

                def at(day):
                    return datetime(2026, 10, day, 12, tzinfo=timezone.utc)

                async def start(user, bot, day, link=None, *, body="/start", message_id=None,
                                sender=SenderType.USER, external_chat_id=None):
                    chat_key = (bot.id, external_chat_id or user)
                    chat = chats.get(chat_key)
                    if chat is None:
                        chat = Chat(project_id=bot.project_id, bot_id=bot.id, external_user_id=user,
                                    external_chat_id=external_chat_id or user,
                                    tracking_link_id=link.id if link else None)
                        db.add(chat)
                        await db.flush()
                        chats[chat_key] = chat
                    values = {"id": message_id} if message_id else {}
                    db.add(Message(chat_id=chat.id, tracking_link_id=link.id if link else None,
                                   sender_type=sender, body=body, created_at=at(day), **values))
                    await db.flush()
                    return chat

                first_chat = await start("111", a, 8, first_link)
                await start("111", a, 8, first_link)
                await start("111", b, 9, second_link)
                await start("111", a, 10, repeat_link)
                await start("222", a, 7, first_link, body="/START@first_bot ref_source")
                await start("222", b, 9, second_link)
                unattributed_chat = await start("333", a, 8)
                await start("333", b, 9, second_link)
                # Identical timestamps still have one stable winner.
                await start("444", a, 9, first_link, message_id=UUID(int=1))
                await start("444", b, 9, second_link, message_id=UUID(int=2))
                await start("111", other_bot, 9)
                await start("", a, 9, first_link, external_chat_id="legacy-a")
                await start("", b, 9, second_link, external_chat_id="legacy-b")
                await start("ignored", a, 9, body="/start", sender=SenderType.MANAGER)
                await start("ignored", b, 9, body="Hello")
                await db.commit()
                repo = TrackingMetricsRepository(db)
                since, until = date(2026, 10, 7), date(2026, 10, 10)

                assert await repo.aggregate_starts_by_project(project.id, None, since, until) == 6
                assert await repo.aggregate_starts_by_project(project.id, a.id, since, until) == 5
                assert await repo.aggregate_starts_by_project(project.id, b.id, since, until) == 1
                assert await repo.aggregate_starts_by_project(other.id, other_bot.id, since, until) == 1
                assert await repo.aggregate_starts_by_project(project.id, b.id, date(2026, 10, 9), until) == 1
                assert await repo.aggregate_starts_by_project(project.id, a.id, until, until) == 0
                assert await repo.aggregate_starts_by_link(first_link.id, since, until) == 4
                assert await repo.aggregate_starts_by_link(second_link.id, since, until) == 1
                assert await repo.aggregate_starts_by_link(repeat_link.id, since, until) == 0
                assert await repo.aggregate_starts_unattributed_by_project(project.id, None, since, until) == 1

                daily = {}
                await repo._merge_daily_starts(daily, project.id, None, None, since, until)
                assert {day: values["starts"] for day, values in daily.items()} == {
                    date(2026, 10, 7): 1, date(2026, 10, 8): 2, date(2026, 10, 9): 3,
                }
                rows = await repo.get_link_metrics_rows(project.id, None, since, until)
                assert {row["link_id"]: row["starts"] for row in rows} == {
                    first_link.id: 4, second_link.id: 1, repeat_link.id: 0,
                }
                assert sum(row["spend"] for row in rows) == Decimal("5")
                link_scope = {}
                await repo._merge_daily_starts(link_scope, project.id, b.id, second_link.id, since, until)
                assert sum(row["starts"] for row in link_scope.values()) == 1
                assert await repo.aggregate_spend_by_project(project.id, None, since, until) == Decimal("5")
                legacy = await TrackingLinkRepository(db).get_traffic_stats(project.id)
                assert {row[0].id: row.chat_clicks for row in legacy} == {
                    first_link.id: 4, second_link.id: 1, repeat_link.id: 0,
                }

                role = Role(name="buyer")
                db.add(role)
                await db.flush()
                buyer = User(role_id=role.id, project_id=project.id, email="buyer@example.test",
                             name="Buyer", password_hash="unused-in-statistics-test")
                db.add(buyer)
                await db.flush()
                second_link.buyer_id = buyer.id
                await db.flush()
                rows = await repo.get_link_metrics_rows(project.id, None, since, until, buyer_id=buyer.id)
                assert [(row["link_id"], row["starts"]) for row in rows] == [(second_link.id, 1)]
                buyer_daily = {}
                await repo._merge_daily_starts(buyer_daily, project.id, None, None, since, until, buyer_id=buyer.id)
                assert sum(row["starts"] for row in buyer_daily.values()) == 1

                # Hiding/resetting the original chat cannot credit another bot.
                first_chat.is_deleted = True
                unattributed_chat.reset_at = at(10)
                await db.flush()
                assert await repo.aggregate_starts_by_project(project.id, b.id, since, until) == 1
                assert await repo.aggregate_starts_by_link(second_link.id, since, until) == 1
                # Chat attribution may change without changing the first start's link.
                first_chat.is_deleted = False
                first_chat.tracking_link_id = repeat_link.id
                await db.flush()
                legacy = await TrackingLinkRepository(db).get_traffic_stats(project.id)
                assert {row[0].id: row.chat_clicks for row in legacy} == {
                    first_link.id: 4, second_link.id: 1, repeat_link.id: 0,
                }
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await root.dispose()

    asyncio.run(run())
