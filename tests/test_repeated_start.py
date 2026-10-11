"""Repeated-start behavior against PostgreSQL, without Telegram transport mocks."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Message, Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelEdge, FunnelScheduledJob
from app.models.lead_status import LeadStatus
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.telegram_service import TelegramService
from app.schemas.telegram import TelegramUpdate, TelegramMessage, TelegramChat, TelegramUser


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_repeated_start_advances_engagement_and_preserves_following_answer():
    async def run():
        schema = "restart_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project, status = Project(name="Restart", slug="restart"), LeadStatus(name="New", code="new")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="Bot")
                db.add(bot); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Restart")
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush()
                bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, version.id
                funnel.current_version_id = version.id
                engagement = FunnelStep(funnel_version_id=version.id, key="engagement", title="Engagement", step_type="message", block_type="generic_message",
                    config_json={"messages": [{"text": "Continue?", "wait_for_answer": True}]})
                phone = FunnelStep(funnel_version_id=version.id, key="phone", title="Phone", step_type="input", block_type="generic_input",
                    config_json={"prompt": " ", "field_key": "phone", "answer_type": "phone", "timeout_seconds": 0})
                final = FunnelStep(funnel_version_id=version.id, key="final", title="Final", step_type="input", block_type="generic_input", config_json={"prompt": " ", "timeout_seconds": 0})
                db.add_all([engagement, phone, final]); await db.flush()
                edge = FunnelEdge(funnel_version_id=version.id, from_step_id=engagement.id, to_step_id=phone.id, condition_json={"source_key": "message:next"})
                db.add_all([edge, FunnelEdge(funnel_version_id=version.id, from_step_id=phone.id, to_step_id=final.id, condition_json={"source_key": "input:next"})])
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="12345", external_user_id="12345")
                db.add(chat); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id)
                state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id, current_step_id=engagement.id,
                    entered_step_at=datetime.now(timezone.utc) - timedelta(minutes=1), waiting_for_answer=True,
                    runtime_json={"message_sequence": {"step_id": str(engagement.id), "message_index": 0}, "message_auto_advance": {"old": True}})
                db.add_all([lead, state]); await db.flush()
                runtime = FunnelRuntimeService(db)
                state.is_paused = True
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id) == "paused"
                assert state.current_step_id == engagement.id
                state.is_paused = False
                edge.condition_json = {"source_key": "message:button:choice", "value": "choice"}
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id) == "button_choice_required"
                assert state.waiting_for_answer
                edge.condition_json = {"source_key": "message:next"}
                await db.commit()
                service = TelegramService(db)
                await service.handle_update(update=TelegramUpdate(update_id=1, message=TelegramMessage(
                    message_id=10, chat=TelegramChat(id=12345), from_user=TelegramUser(id=12345, first_name="Anna"), text="/start")),
                    project_id=project.id, bot_id=bot.id)
                start = await db.scalar(select(Message).where(Message.chat_id == chat.id, Message.body == "/start"))
                assert start.raw_payload_json["crm_repeated_start"] is True
                await db.refresh(chat)
                assert chat.has_restarted_bot is True
                start.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
                reply = Message(chat_id=chat.id, sender_type="user", body="+998901234567", created_at=datetime.now(timezone.utc) - timedelta(seconds=7))
                db.add(reply); await db.commit()
                assert await service.process_debounced_user_input(chat_id=chat.id, trigger_message_id=reply.id) == "processed"
                await db.refresh(state); await db.refresh(lead)
                assert state.current_step_id == final.id
                assert lead.phone == "+998901234567"
                assert state.runtime_json["last_engagement"]["type"] == "repeated_start"
                assert "message_auto_advance" not in state.runtime_json
                await db.refresh(start); await db.refresh(reply)
                assert start.funnel_processed_at and reply.funnel_processed_at
                # Duplicate delivery does not consume another step or repeat processing.
                assert await service.process_debounced_user_input(chat_id=chat.id, trigger_message_id=reply.id) == "already_processed"
                # A fast reply survives a delayed prompt, including a worker/session restart.
                state.current_step_id = engagement.id
                state.waiting_for_answer = True
                state.runtime_json = {"message_sequence": {"step_id": str(engagement.id), "message_index": 0}}
                phone.config_json = {**phone.config_json, "prompt_delay_seconds": 30}
                later_start = Message(chat_id=chat.id, sender_type="user", body="/start", raw_payload_json={"crm_repeated_start": True}, created_at=datetime.now(timezone.utc) - timedelta(seconds=6))
                later_reply = Message(chat_id=chat.id, sender_type="user", body="+998909876543", created_at=datetime.now(timezone.utc) - timedelta(seconds=4))
                db.add_all([later_start, later_reply]); await db.commit()
                outcome = await service.process_debounced_user_input(chat_id=chat.id, trigger_message_id=later_reply.id)
                assert outcome.startswith("pending_runtime:")
                await db.commit()
                await db.refresh(later_start); await db.refresh(later_reply)
                assert later_start.funnel_processed_at is not None
                assert later_reply.funnel_processed_at is None
                job = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.chat_id == chat.id, FunnelScheduledJob.status == "pending", FunnelScheduledJob.job_type == "input_prompt"))
                assert job is not None
                await runtime.process_scheduled_job(job)
                await db.commit()
                assert await TelegramService(db).process_debounced_user_input(chat_id=chat.id, trigger_message_id=later_reply.id) == "processed"
                await db.refresh(lead); await db.refresh(state); await db.refresh(later_reply)
                assert lead.phone == "+998909876543"
                assert state.current_step_id == final.id
                assert later_reply.funnel_processed_at is not None
                state.current_step_id = phone.id
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id) == "data_answer_required"
                assert lead.phone == "+998909876543"
                state.completed_at = datetime.now(timezone.utc)
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id) == "inactive"
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
