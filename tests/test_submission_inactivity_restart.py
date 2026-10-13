"""Explicit submission re-entry after inactivity, against real PostgreSQL."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Message, Project, Tag
from app.models.chat_event_log import ChatEventLog
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelEdge, FunnelScheduledJob
from app.models.lead import LeadTag
from app.models.lead_status import LeadStatus
from app.repositories.tracking_start_query import is_first_project_start
from app.schemas.message import MessageOut
from app.schemas.telegram import TelegramUpdate, TelegramMessage, TelegramChat, TelegramUser
from app.services.telegram_service import TelegramService
from app.services.funnel_runtime_service import FunnelRuntimeService


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
@pytest.mark.parametrize("project_format,idle_days,lifecycle,imported,recent_input,expected,same_version", [
    ("submission", 30, "active", False, False, True, False),
    ("submission", 31, "paused", False, False, True, False),
    ("submission", 31, "completed", False, False, True, False),
    ("submission", 31, "active", False, False, True, True),
    ("submission", 29, "completed", False, False, False, False),
    ("gambling", 31, "completed", False, False, False, False),
    ("submission", 31, "completed", True, False, False, False),
    ("submission", 31, "completed", False, True, False, False),
])
def test_only_explicit_idle_start_restarts_current_published_funnel(
    project_format, idle_days, lifecycle, imported, recent_input, expected, same_version,
):
    async def run():
        schema = "idle_restart_" + uuid4().hex
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
                now = datetime.now(timezone.utc) - timedelta(seconds=10)
                previous = now - timedelta(days=idle_days)
                project = Project(name="Submission restart", slug="submission-restart", project_format=project_format)
                status = LeadStatus(name="Qualified", code="qualified")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="Bot")
                tag = Tag(project_id=project.id, name="VIP")
                db.add_all([bot, tag]); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Current funnel")
                db.add(funnel); await db.flush()
                old_version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="archived")
                version = FunnelVersion(funnel_id=funnel.id, version_number=2, status="published")
                db.add_all([old_version, version]); await db.flush()
                bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, version.id
                funnel.current_version_id = version.id
                old_step = FunnelStep(funnel_version_id=old_version.id, key="old", title="Old", step_type="input",
                    block_type="generic_input", config_json={"field_key": "phone", "answer_type": "phone", "prompt": " "})
                trigger = FunnelStep(funnel_version_id=version.id, key="start", title="Start", step_type="trigger", block_type="generic_start",
                    config_json={"repeat_start_defaults": {"mode": "remind", "text": ""}})
                phone = FunnelStep(funnel_version_id=version.id, key="phone", title="Phone", step_type="input",
                    block_type="generic_input", config_json={"field_key": "phone", "answer_type": "phone", "prompt": " ", "prompt_delay_seconds": 30})
                age = FunnelStep(funnel_version_id=version.id, key="age", title="Age", step_type="input",
                    block_type="generic_input", config_json={"field_key": "age", "answer_type": "number", "prompt": " "})
                db.add_all([old_step, trigger, phone, age]); await db.flush()
                db.add_all([FunnelEdge(funnel_version_id=version.id, from_step_id=trigger.id, to_step_id=phone.id),
                    FunnelEdge(funnel_version_id=version.id, from_step_id=phone.id, to_step_id=age.id,
                               condition_json={"source_key": "input:answer"})])
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="12345", external_user_id="12345",
                    is_imported=imported, created_at=previous - timedelta(days=30), last_user_message_at=previous,
                    unanswered_push_count=3)
                db.add(chat); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id,
                    name="Anna", phone="+998909876543", manager_comment="Keep comment", custom_fields={"budget": 100})
                previous_version_id = version.id if same_version else old_version.id
                previous_step_id = phone.id if same_version else old_step.id
                state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=previous_version_id,
                    current_step_id=previous_step_id, entered_step_at=previous - timedelta(minutes=1), waiting_for_answer=True,
                    is_paused=lifecycle == "paused", completed_at=previous if lifecycle == "completed" else None,
                    runtime_json={"push_rules_sent": {"old": "visit"}, "last_answer": "old"})
                history = Message(chat_id=chat.id, sender_type="user", body="/start", created_at=previous,
                    funnel_processed_at=previous, deleted_at=previous if lifecycle == "paused" else None)
                db.add_all([lead, state, history]); await db.flush()
                db.add(LeadTag(lead_id=lead.id, tag_id=tag.id))
                old_job = FunnelScheduledJob(chat_id=chat.id, funnel_state_id=state.id, funnel_id=funnel.id,
                    funnel_version_id=previous_version_id, step_id=previous_step_id, job_type="input_timeout",
                    run_at=now + timedelta(days=1), status="running" if lifecycle == "paused" else "pending")
                obsolete_job = FunnelScheduledJob(chat_id=chat.id, funnel_state_id=state.id, funnel_id=funnel.id,
                    funnel_version_id=previous_version_id, step_id=previous_step_id, job_type="input_timeout",
                    run_at=now, status="running")
                db.add(old_job)
                if recent_input:
                    db.add(Message(chat_id=chat.id, sender_type="user", body="Recent reply",
                                   created_at=now - timedelta(days=1), funnel_processed_at=now))
                await db.commit()
                chat_id, project_id, bot_id = chat.id, project.id, bot.id
                service = TelegramService(db)
                # Inactivity alone schedules nothing and a named-account message cannot trigger this policy.
                assert not await service._submission_restart_after_inactivity(chat,
                    MessageOut.model_validate(history).model_copy(update={"body": "Hello", "created_at": now}), state)
                assert not await service._submission_restart_after_inactivity(chat,
                    MessageOut.model_validate(history).model_copy(update={"transport_source": "user_mtproto", "created_at": now}), state)
                await db.refresh(state)
                assert state.funnel_version_id == previous_version_id
                await service.handle_update(update=TelegramUpdate(update_id=1, message=TelegramMessage(
                    message_id=10, chat=TelegramChat(id=12345), from_user=TelegramUser(id=12345, first_name="Anna"), text="/start")),
                    project_id=project_id, bot_id=bot_id)
                command = await db.scalar(select(Message).where(Message.chat_id == chat_id, Message.external_message_id == "10"))
                command.created_at = now
                await db.commit()
                assert await service.process_debounced_user_input(chat_id=chat_id, trigger_message_id=command.id) == "processed"
                await db.commit()
                state = await db.scalar(select(ChatFunnelState).where(ChatFunnelState.chat_id == chat_id))
                await db.refresh(state); await db.refresh(lead); await db.refresh(chat); await db.refresh(old_job)
                assert state.funnel_version_id == (version.id if expected else previous_version_id)
                assert lead.phone == "+998909876543" and lead.manager_comment == "Keep comment"
                assert lead.status_id == status.id and lead.custom_fields["budget"] == 100
                assert await db.scalar(select(func.count()).select_from(LeadTag).where(LeadTag.lead_id == lead.id)) == 1
                assert await db.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat_id)) == (3 if recent_input else 2)
                assert await db.scalar(select(func.count()).select_from(Message).join(Chat, Chat.id == Message.chat_id)
                    .where(Chat.id == chat_id, is_first_project_start())) == 1
                assert await service.process_debounced_user_input(chat_id=chat_id, trigger_message_id=command.id) == "already_processed"
                if expected:
                    assert state.current_step_id == phone.id and state.completed_at is None and not state.is_paused
                    assert old_job.status == "cancelled"
                    assert old_job.funnel_state_id is None
                    await FunnelRuntimeService(db).process_scheduled_job(obsolete_job)
                    await db.refresh(state)
                    assert state.current_step_id == phone.id and state.completed_at is None
                    assert "push_rules_sent" not in state.runtime_json
                    assert state.runtime_json["last_engagement"]["type"] == "inactivity_restart"
                    assert chat.unanswered_push_count == 0
                    assert await db.scalar(select(func.count()).select_from(ChatEventLog).where(
                        ChatEventLog.chat_id == chat_id, ChatEventLog.new_value.like("Повторный /start после 30 дней%"))) == 1
                    reply = Message(chat_id=chat_id, sender_type="user", body="+998901234567", created_at=now + timedelta(seconds=3))
                    db.add(reply); await db.commit()
                    outcome = await service.process_debounced_user_input(chat_id=chat_id, trigger_message_id=reply.id)
                    assert outcome.startswith("pending_runtime:")
                    await db.commit()
                    job = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.chat_id == chat_id,
                        FunnelScheduledJob.job_type == "input_prompt", FunnelScheduledJob.status == "pending"))
                    await FunnelRuntimeService(db).process_scheduled_job(job)
                    await db.commit()
                    assert await TelegramService(db).process_debounced_user_input(chat_id=chat_id, trigger_message_id=reply.id) == "processed"
                    await db.commit()
                    await db.refresh(state); await db.refresh(lead); await db.refresh(reply)
                    assert state.current_step_id == age.id and lead.phone == "+998901234567"
                    assert reply.funnel_processed_at is not None
                    delay = FunnelStep(funnel_version_id=version.id, key="wait", title="Wait", step_type="delay",
                        block_type="generic_delay", config_json={"delay_type": "no_reply_timeout", "delay_seconds": 30})
                    db.add(delay); await db.flush()
                    state.current_step_id = delay.id
                    await db.flush()
                    runtime = FunnelRuntimeService(db)
                    await runtime._execute_delay_step(chat_id=chat_id, step=delay)
                    answered = Message(chat_id=chat_id, sender_type="user", body="Answered", created_at=now + timedelta(seconds=4))
                    db.add(answered); await db.commit()
                    assert await TelegramService(db).process_debounced_user_input(chat_id=chat_id, trigger_message_id=answered.id) == "processed"
                    await db.refresh(state)
                    assert state.runtime_json["no_reply"][str(delay.id)]["replied"] is True
                    timeout = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.chat_id == chat_id,
                        FunnelScheduledJob.job_type == "no_reply_timeout", FunnelScheduledJob.status == "pending"))
                    await runtime.process_scheduled_job(timeout)
                    await db.refresh(state)
                    assert state.current_step_id == delay.id and state.completed_at is None
                else:
                    assert old_job.status == "pending"
                    assert chat.unanswered_push_count == 3
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
