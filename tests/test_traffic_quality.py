import asyncio
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.base import Base
from app.models.project import Project
from app.models.bot import Bot
from app.models.role import Role
from app.models.user import User
from app.models.chat import Chat
from app.models.lead import Lead, LeadTag
from app.models.tag import Tag
from app.models.lead_status import LeadStatus
from app.models.lead_event import LeadEvent
from app.models.tracking import TrackingLink
from app.models.traffic_quality import TrafficQualityState, TrafficQualityDelivery, TrafficQualityAcknowledgement
from app.schemas.traffic_quality import QualityConfig, QualityRule, QualityOverrides, effective_rules
from app.services.traffic_expression import evaluate_expression, parse_expression
from app.services.traffic_quality_service import TrafficQualityService, evaluate_rule
from app.repositories.traffic_quality_repository import TrafficQualityRepository
from app.workers.traffic_quality_worker import deliver_quality


@pytest.mark.parametrize("expression", ["__import__('os')", "leads.__class__", "[leads][0]", "2 ** 1000", "sum(leads)", "lambda: 1", "True", "1e999", "percent(leads)", "percent(leads, 2, 3)"])
def test_expression_rejects_unsafe_syntax(expression):
    with pytest.raises(ValueError):
        parse_expression(expression)


@pytest.mark.parametrize("expression,metrics,result", [
    ("percent(tagged_leads, leads)", {"tagged_leads": 3, "leads": 10}, 30),
    ("percent(first_deposits, registrations)", {"first_deposits": 2, "registrations": 0}, None),
    ("spend / leads", {"leads": 3}, None),
    ("max(0, leads - 10)", {"leads": 3}, 0),
    ("leads > 20 and coverage >= 80", {"leads": 30, "coverage": 90}, 1),
    ("leads > 20 or coverage >= 80", {"leads": 10, "coverage": 90}, 1),
    ("leads > 20 and coverage >= 80", {"leads": 30}, None),
])
def test_expression_values_and_missing_data(expression, metrics, result):
    assert evaluate_expression(expression, metrics) == result


def conversion_rule(**kwargs):
    return QualityRule(name="Conversion", expression="percent(registrations, leads)", operator="lt", threshold=10,
                       recovery_threshold=15, sample_metric="leads", **kwargs)


def test_safe_defaults_inheritance_and_validation():
    assert not QualityConfig().enabled
    rule = conversion_rule()
    config = QualityConfig(rules=[rule])
    overrides = QualityOverrides(patches={rule.id: {"threshold": 5}})
    assert effective_rules(config, overrides)[0].threshold == 5
    config.rules[0].min_sample = 99
    assert effective_rules(config, overrides)[0].min_sample == 99
    assert effective_rules(config, QualityOverrides())[0].threshold == 10
    with pytest.raises(ValidationError):
        QualityRule(name="Bad", tag_ids=[uuid4()])
    with pytest.raises(ValueError):
        effective_rules(config, QualityOverrides(patches={rule.id: {"unknown": True}}))


def test_minimum_sample_and_coverage_never_report_bad_traffic():
    rule = conversion_rule(min_sample=40)
    assert evaluate_rule(rule, {"metrics": {"leads": 20, "registrations": 0}})["status"] == "insufficient_data"
    assert evaluate_rule(rule, {"metrics": {"leads": 40, "registrations": 0}})["status"] == "breach"
    assert evaluate_rule(rule, {"metrics": {"leads": 40, "registrations": 6}})["recovered"]


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable local PostgreSQL required")
def test_postgres_cohorts_rules_outbox_permissions_and_migration():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = f"quality_{uuid4().hex}"
        admin_engine = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        spec = importlib.util.spec_from_file_location("quality_migration", Path(__file__).resolve().parents[1] / "alembic/versions/20261002_0079_traffic_quality.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        def migrate(conn, direction):
            with Operations.context(MigrationContext.configure(conn)):
                getattr(migration, direction)()

        try:
            async with admin_engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(migrate, "downgrade")
                await conn.run_sync(migrate, "upgrade")
            now = datetime.now(timezone.utc)
            async with sessions() as db:
                project = Project(name="Quality", slug="quality")
                other_project = Project(name="Other", slug="other")
                admin_role, buyer_role = Role(name="admin"), Role(name="buyer")
                db.add_all([project, other_project, admin_role, buyer_role])
                await db.flush()
                admin = User(email="admin@test.local", name="Admin", password_hash="not-a-login", role=admin_role, project_id=project.id)
                buyer = User(email="buyer@test.local", name="Buyer", password_hash="not-a-login", role=buyer_role, project_id=project.id)
                outsider = User(email="other@test.local", name="Other", password_hash="not-a-login", role=buyer_role, project_id=other_project.id)
                bot = Bot(project_id=project.id, name="Bot")
                personal = Bot(project_id=project.id, name="Account", transport_type="user_mtproto")
                status = LeadStatus(code="qualified", name="Qualified")
                risk, minor = Tag(project_id=project.id, name="Risk"), Tag(project_id=project.id, name="Under 18")
                db.add_all([admin, buyer, outsider, bot, personal, status, risk, minor])
                await db.flush()
                link = TrackingLink(project_id=project.id, bot_id=bot.id, name="Test", title="Test", code="quality", ref_code="quality", buyer_id=buyer.id)
                db.add(link)
                await db.flush()
                leads = []
                for user_id, which_bot, age in [("100", bot, 3), ("100", personal, 2), ("200", bot, 3), ("300", bot, 0), ("400", bot, 12)]:
                    chat = Chat(project_id=project.id, bot_id=which_bot.id, tracking_link_id=link.id, external_chat_id=user_id,
                                external_user_id=user_id, created_at=now - timedelta(days=age))
                    db.add(chat)
                    await db.flush()
                    lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id)
                    db.add(lead)
                    await db.flush()
                    leads.append(lead)
                db.add_all([LeadTag(lead_id=leads[0].id, tag_id=risk.id), LeadTag(lead_id=leads[1].id, tag_id=minor.id), LeadTag(lead_id=leads[2].id, tag_id=risk.id)])
                for lead in leads[:2]:
                    for source in ("tag", "postback"):
                        db.add(LeadEvent(project_id=project.id, lead_id=lead.id, tracking_link_id=link.id,
                                         event_type="registration", source=source, occurred_at=now - timedelta(hours=20)))
                db.add(LeadEvent(project_id=project.id, lead_id=leads[1].id, tracking_link_id=link.id,
                                event_type="deposit", source="postback", occurred_at=now - timedelta(hours=10)))
                await db.commit()
                service = TrafficQualityService(db)
                assert not (await service.config(project.id)).enabled
                rule = QualityRule(name="Bad traffic", tag_ids=[risk.id, minor.id], assessed_status_codes=[status.code], min_sample=2)
                config = await service.save_config(project.id, admin, QualityConfig(enabled=True, rules=[rule]))
                await db.commit()
                with pytest.raises(HTTPException) as exc:
                    await service.save_config(project.id, buyer, config)
                assert exc.value.status_code == 403
                with pytest.raises(HTTPException) as exc:
                    await service.link(link.id, outsider)
                assert exc.value.status_code == 403
                with pytest.raises(HTTPException) as exc:
                    await service.save_config(project.id, admin, QualityConfig())
                assert exc.value.status_code == 409
                metrics = (await TrafficQualityRepository(db).metrics(project, link, rule, now))["metrics"]
                assert metrics["leads"] == 2
                assert metrics["tagged_leads"] == 2
                assert metrics["assessed_leads"] == 2
                assert metrics["registrations"] == 1
                assert metrics["registered_depositors"] == 1
                assert metrics["clicks"] is None
                assert (await TrafficQualityRepository(db).metrics(project, link, rule.model_copy(update={"tag_match": "all"}), now))["metrics"]["tagged_leads"] == 1
                await service.check_link(project, link, config)
                await db.commit()
                state = await db.get(TrafficQualityState, (link.id, rule.id))
                assert state.hits == 1 and not state.active
                await service.check_link(project, link, config)
                assert state.hits == 1  # same check cannot satisfy confirmations
                state.checked_at -= timedelta(minutes=15)
                await db.commit()
                await service.check_link(project, link, config)
                await db.commit()
                assert state.active
                assert await db.scalar(select(func.count()).select_from(TrafficQualityDelivery)) == 2
                state.checked_at -= timedelta(minutes=15)
                await db.commit()
                await service.check_link(project, link, config)
                await db.commit()
                assert await db.scalar(select(func.count()).select_from(TrafficQualityDelivery)) == 2
                await service.acknowledge(link.id, buyer, 1)
                await db.commit()
                assert (await db.get(TrafficQualityAcknowledgement, (link.id, buyer.id))).until > now
                await deliver_quality(session_factory=sessions)
                # Acknowledged alerts remain deferred, no Telegram request occurs.
                db.expire_all()
                deliveries = (await db.scalars(select(TrafficQualityDelivery))).all()
                assert all(item.attempts == 0 for item in deliveries if item.bot_kind == "buyer")
                assert all(item.attempts == 1 for item in deliveries if item.bot_kind == "admin")
                assert all(item.available_at > now for item in deliveries)
                # Disabling the project cancels queued notifications, including
                # snoozed deliveries, once their next attempt becomes due.
                await db.refresh(project)
                await db.refresh(admin)
                await db.refresh(admin, ["role", "project_accesses"])
                config = await service.config(project.id)
                config.enabled = False
                await service.save_config(project.id, admin, config)
                for item in deliveries:
                    item.available_at = now - timedelta(seconds=1)
                await db.commit()
                await deliver_quality(session_factory=sessions)
                db.expire_all()
                deliveries = (await db.scalars(select(TrafficQualityDelivery))).all()
                assert all(item.status == "cancelled" for item in deliveries)
            async with engine.begin() as conn:
                await conn.run_sync(migrate, "downgrade")
                assert (await conn.execute(text("SELECT count(*) FROM leads"))).scalar_one() == 5
                await conn.run_sync(migrate, "upgrade")
                assert (await conn.execute(text("SELECT count(*) FROM traffic_quality_settings"))).scalar_one() == 0
        finally:
            await engine.dispose()
            async with admin_engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await admin_engine.dispose()
    asyncio.run(run())
