"""Configured comparisons must not be shadowed by the legacy yes/no mode."""
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Message, Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelEdge, FunnelStep, FunnelVersion
from app.models.lead_status import LeadStatus
from app.services.funnel_runtime_service import FunnelRuntimeService


@pytest.mark.parametrize("conditions,expected", [
    ([], True),
    ([{"source": "last_answer", "field": "", "operator": "equals", "value": "yes"}], True),
    ([{"source": "last_answer", "operator": "gt", "value": "20"}], False),
    ([{"source": "lead_field", "field": "age", "operator": "gt", "value": "20"}], False),
    ([{"source": "tag", "operator": "contains", "value": "VIP"}], False),
    ([{"operator": "equals", "value": "yes"}, {"operator": "gt", "value": "20"}], False),
])
def test_only_original_yes_no_rule_uses_answer_shortcut(conditions, expected):
    config = {"mode": "simple_yes_no", "conditions": conditions}
    assert FunnelRuntimeService._uses_simple_yes_no(config) is expected
    assert not FunnelRuntimeService._uses_simple_yes_no({**config, "mode": "all"})
    assert not FunnelRuntimeService._uses_simple_yes_no({**config, "mode": "any"})


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_age_reply_runs_configured_branch_and_legacy_yes_no_still_works():
    async def run():
        schema = "condition_" + uuid4().hex
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Condition QA", slug="condition-qa")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, status])
                await db.flush()
                bot = Bot(project_id=project.id, name="QA")
                db.add(bot)
                await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Age")
                db.add(funnel)
                await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version)
                await db.flush()
                question = FunnelStep(funnel_version_id=version.id, key="age", title="Age",
                    step_type="input", block_type="generic_input", position_x=0, position_y=0,
                    config_json={"prompt": "Age?", "save_to": "age", "answer_type": "number",
                                 "validation": {"type": "number"}, "max_retries": 2})
                condition = FunnelStep(funnel_version_id=version.id, key="check", title="Check",
                    step_type="condition", block_type="generic_condition", position_x=0, position_y=0)
                accepted = FunnelStep(funnel_version_id=version.id, key="accepted", title="Accepted",
                    step_type="finish", block_type="generic_finish", position_x=0, position_y=0,
                    config_json={"result": "stop"})
                rejected = FunnelStep(funnel_version_id=version.id, key="rejected", title="Rejected",
                    step_type="finish", block_type="generic_finish", position_x=0, position_y=0,
                    config_json={"result": "stop"})
                db.add_all([question, condition, accepted, rejected])
                await db.flush()
                db.add(FunnelEdge(funnel_version_id=version.id, from_step_id=question.id,
                    to_step_id=condition.id, priority=0, condition_json={"source_key": "input:answer"}))
                await db.flush()
                service = FunnelRuntimeService(db)
                # Exactly the conflicting mode/rule combination in the production backup.
                for source in ("last_answer", "lead_field"):
                    condition.config_json = {
                        "mode": "simple_yes_no",
                        "conditions": [{"source": source, "field": "age" if source == "lead_field" else "",
                                        "operator": "gt", "value": "20"}],
                        "outcomes": [
                            {"id": "true", "target_step_id": str(accepted.id)},
                            {"id": "false", "target_step_id": str(rejected.id)},
                            {"id": "fallback", "target_step_id": str(question.id)},
                        ],
                    }
                    await db.flush()
                    for answer, age in (("18", 18), ("20", 20), ("21", 21), ("43 года", 43), ("Мне 36 лет", 36)):
                        external = uuid4().hex
                        chat = Chat(project_id=project.id, bot_id=bot.id,
                                    external_chat_id=external, external_user_id=external)
                        db.add(chat)
                        await db.flush()
                        lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id)
                        state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id,
                            funnel_version_id=version.id, current_step_id=question.id,
                            entered_step_at=datetime.now(timezone.utc), waiting_for_answer=True)
                        message = Message(chat_id=chat.id, sender_type="user", message_type="text", body=answer)
                        db.add_all([lead, state, message])
                        await db.flush()
                        assert await service.process_incoming_message(chat_id=chat.id, text=answer, message_type="text")
                        await db.refresh(state)
                        await db.refresh(lead)
                        await db.refresh(message)
                        assert state.current_step_id == (accepted.id if age > 20 else rejected.id)
                        assert state.completed_at is not None
                        assert lead.age == age
                        assert state.runtime_json["last_answer"] == str(age)
                        assert message.body == answer
                        assert await db.scalar(select(func.count(Message.id)).where(Message.chat_id == chat.id)) == 1

                condition.config_json = {"mode": "simple_yes_no", "conditions": [
                    {"source": "last_answer", "field": "", "operator": "equals", "value": "yes"}]}
                for answer, outcome in (("да", "true"), ("ага", "true"), ("yes", "true"),
                                        ("нет", "false"), ("no", "false"), ("43", "fallback")):
                    assert await service._evaluate_condition_outcome(
                        chat_id=chat.id, step=condition, answer=answer) == outcome
                await db.rollback()
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
