"""Repeated-start behavior against PostgreSQL, without Telegram transport mocks."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Message, Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelEdge, FunnelScheduledJob, FunnelStepLog, FunnelPushRule
from app.repositories.funnel_repository import FunnelRepository
from app.models.lead_status import LeadStatus
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.telegram_service import TelegramService
from app.schemas.telegram import TelegramUpdate, TelegramMessage, TelegramChat, TelegramUser


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_repeated_start_preserves_push_clock_count_and_sent_markers():
    async def run():
        schema = "restart_push_" + uuid4().hex
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
                project = Project(name="Push restart", slug="push-restart", project_format="gambling")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="Bot")
                db.add(bot); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Push restart")
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush()
                bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, version.id
                funnel.current_version_id = version.id
                age = FunnelStep(funnel_version_id=version.id, key="age", title="Age", step_type="input",
                    block_type="generic_input", config_json={"prompt": " ", "field_key": "age", "answer_type": "number"})
                db.add(age); await db.flush()
                now = datetime.now(timezone.utc)
                entered = now - timedelta(minutes=10)
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="12345", external_user_id="12345",
                    unanswered_push_count=2)
                db.add(chat); await db.flush()
                rules = [FunnelPushRule(funnel_version_id=version.id, step_id=age.id,
                    delay_minutes=delay, message_text="Reminder") for delay in (3, 5, 20)]
                db.add_all(rules); await db.flush()
                sent = {str(rules[0].id): entered.isoformat()}
                state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=age.id, entered_step_at=entered, waiting_for_answer=True,
                    runtime_json={"push_rules_sent": sent})
                db.add_all([state, Lead(project_id=project.id, chat_id=chat.id, status_id=status.id)])
                await db.commit()
                chat_id, project_id, bot_id = chat.id, project.id, bot.id
                for index, command in enumerate(("/start", "/start referral"), start=1):
                    await TelegramService(db).handle_update(update=TelegramUpdate(update_id=index,
                        message=TelegramMessage(message_id=index, chat=TelegramChat(id=12345),
                            from_user=TelegramUser(id=12345, first_name="Anna"), text=command)),
                        project_id=project_id, bot_id=bot_id)
                    await db.commit()
                    assert await FunnelRuntimeService(db).process_repeated_start(chat_id=chat_id) == "data_answer_required"
                    await db.refresh(chat); await db.refresh(state)
                    assert chat.unanswered_push_count == 2
                    assert chat.last_user_message_at is not None
                    assert chat.has_restarted_bot
                    assert state.entered_step_at == entered
                    assert state.runtime_json["push_rules_sent"] == sent
                    candidates = await FunnelRepository(db).find_stuck_chats_for_push_rules(now=now)
                    assert [rule.id for _, rule in candidates] == [rules[1].id]
                # An actual reply still clears the unanswered-push counter.
                await TelegramService(db).handle_update(update=TelegramUpdate(update_id=3,
                    message=TelegramMessage(message_id=3, chat=TelegramChat(id=12345),
                        from_user=TelegramUser(id=12345, first_name="Anna"), text="25")),
                    project_id=project_id, bot_id=bot_id)
                await db.commit()
                await db.refresh(chat)
                assert chat.unanswered_push_count == 0
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())


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


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_start_engagement_survives_delay_and_advances_free_question_not_required_fields():
    async def run():
        schema = "engagement_" + uuid4().hex
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
                project = Project(name="Engagement", slug="engagement")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="Bot")
                db.add(bot); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Engagement")
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush()
                bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, version.id
                funnel.current_version_id = version.id
                delivery = FunnelStep(funnel_version_id=version.id, key="delivery", title="Delivery",
                    step_type="message", block_type="generic_message",
                    config_json={"messages": [{"text": "", "wait_for_answer": True, "delay_seconds": 30}]})
                word = FunnelStep(funnel_version_id=version.id, key="word", title="Word",
                    step_type="input", block_type="generic_input", config_json={"prompt": " ", "answer_type": "text"})
                phone = FunnelStep(funnel_version_id=version.id, key="phone", title="Phone",
                    step_type="input", block_type="generic_input", config_json={"prompt": " ", "save_to": "phone", "answer_type": "phone"})
                age = FunnelStep(funnel_version_id=version.id, key="age", title="Age",
                    step_type="input", block_type="generic_input", config_json={"prompt": " ", "save_to": "age", "answer_type": "number"})
                db.add_all([delivery, word, phone, age]); await db.flush()
                db.add_all([
                    FunnelEdge(funnel_version_id=version.id, from_step_id=delivery.id, to_step_id=word.id,
                               condition_json={"source_key": "message:next"}),
                    FunnelEdge(funnel_version_id=version.id, from_step_id=word.id, to_step_id=phone.id,
                               condition_json={"source_key": "input:answer"}),
                    FunnelEdge(funnel_version_id=version.id, from_step_id=phone.id, to_step_id=age.id,
                               condition_json={"source_key": "input:answer"}),
                ])
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="42", external_user_id="42")
                db.add(chat); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, age=33, phone="+998901234567")
                state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=delivery.id, entered_step_at=datetime.now(timezone.utc), waiting_for_answer=False)
                db.add_all([lead, state]); await db.flush()
                job = FunnelScheduledJob(chat_id=chat.id, funnel_state_id=state.id, funnel_id=funnel.id,
                    funnel_version_id=version.id, step_id=delivery.id, job_type="message_sequence", status="running",
                    payload_json={"message_index": 0}, run_at=datetime.now(timezone.utc) + timedelta(seconds=30))
                first_start = Message(chat_id=chat.id, sender_type="user", body="/start",
                    raw_payload_json={"crm_repeated_start": True}, created_at=datetime.now(timezone.utc) - timedelta(seconds=10))
                db.add_all([job, first_start]); await db.flush()
                runtime = FunnelRuntimeService(db)
                assert await runtime.process_repeated_start(chat_id=chat.id, message_id=first_start.id) == "engagement_pending"
                assert await runtime.process_repeated_start(chat_id=chat.id, message_id=uuid4()) == "engagement_pending"
                assert state.runtime_json["pending_start_engagement"]["message_id"] == str(first_start.id)
                await TelegramService(db).message_repo.claim_funnel_processing([first_start.id])
                await db.commit()
                chat_id, state_id, job_id, word_id, phone_id, age_id, first_id = chat.id, state.id, job.id, word.id, phone.id, age.id, first_start.id

            # A fresh worker/session consumes the durable signal only when ready.
            async with sessions() as db:
                runtime = FunnelRuntimeService(db)
                job = await db.get(FunnelScheduledJob, job_id)
                await runtime.process_scheduled_job(job)
                state = await db.get(ChatFunnelState, state_id)
                assert state.current_step_id == word_id and state.waiting_for_answer
                assert "pending_start_engagement" not in state.runtime_json
                assert state.runtime_json["last_engagement"]["message_id"] == str(first_id)
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=first_id) == "already_processed"
                second_start = Message(chat_id=chat_id, sender_type="user", body="/start",
                    raw_payload_json={"crm_repeated_start": True}, created_at=datetime.now(timezone.utc) - timedelta(seconds=8))
                answer = Message(chat_id=chat_id, sender_type="user", body="+998909876543",
                    created_at=datetime.now(timezone.utc) - timedelta(seconds=5))
                db.add_all([second_start, answer]); await db.commit()
                assert await TelegramService(db).process_debounced_user_input(chat_id=chat_id, trigger_message_id=answer.id) == "processed"
                await db.refresh(state)
                lead = await db.scalar(select(Lead).where(Lead.chat_id == chat_id))
                assert state.current_step_id == age_id and state.waiting_for_answer
                assert lead.phone == "+998909876543" and lead.age == 33
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "data_answer_required"
                state.current_step_id = phone_id
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "data_answer_required"
                assert lead.phone == "+998909876543" and lead.age == 33
                await db.refresh(second_start); await db.refresh(answer)
                assert second_start.funnel_processed_at and answer.funnel_processed_at
                assert second_start.body == "/start" and answer.body == "+998909876543"
                answered = (await db.scalars(select(FunnelStepLog.step_id).where(
                    FunnelStepLog.lead_id == lead.id, FunnelStepLog.event_type == "answered"))).all()
                assert answered.count(word_id) == 1
                assert answered.count(delivery.id) == 1

                delivery_step = await db.get(FunnelStep, delivery.id)
                # Retained legacy single-message waits may have no sequence marker.
                delivery_step.config_json = {"text": "Legacy continue", "wait_for_answer": True}
                state.current_step_id = delivery_step.id
                state.entered_step_at = datetime.now(timezone.utc)
                state.waiting_for_answer = True
                state.runtime_json = {}
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "continued"
                assert state.current_step_id == word_id

                # Buttons on a later message must not block the current free wait.
                delivery_step.config_json = {"messages": [
                    {"text": "", "wait_for_answer": True},
                    {"text": "", "wait_for_answer": True, "buttons": [
                        {"id": "choice", "label": "Choice", "type": "branch", "target_step_id": str(phone_id)}]},
                ]}
                db.add(FunnelEdge(funnel_version_id=version.id, from_step_id=delivery_step.id, to_step_id=phone_id,
                    priority=-1, condition_json={"source_key": "message:1:button:choice", "value": "choice"}))
                state.current_step_id = delivery_step.id
                state.entered_step_at = datetime.now(timezone.utc)
                state.waiting_for_answer = True
                state.runtime_json = {"message_sequence": {"step_id": str(delivery_step.id), "message_index": 0}}
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "continued"
                assert state.current_step_id == delivery_step.id
                assert state.runtime_json["message_sequence"]["message_index"] == 1
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "continued"
                assert state.current_step_id == word_id  # Never the first, button-specific edge.

                # The chosen default survives another scheduled message delay.
                delivery_step.config_json = {"messages": [
                    {"text": "", "wait_for_answer": True}, {"text": "", "delay_seconds": 30},
                ]}
                state.current_step_id = delivery_step.id
                state.entered_step_at = datetime.now(timezone.utc)
                state.waiting_for_answer = True
                state.runtime_json = {"message_sequence": {"step_id": str(delivery_step.id), "message_index": 0}}
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "continued"
                continuation = await db.scalar(select(FunnelScheduledJob).where(
                    FunnelScheduledJob.chat_id == chat_id, FunnelScheduledJob.step_id == delivery_step.id,
                    FunnelScheduledJob.status == "pending", FunnelScheduledJob.job_type == "message_sequence")
                    .order_by(FunnelScheduledJob.created_at.desc()).limit(1))
                assert continuation is not None and continuation.payload_json["completion_edge_id"]
                continuation.run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.flush()
                await runtime.process_scheduled_job(continuation)
                assert state.current_step_id == word_id

                # A valid configured timer path is also a deterministic continuation.
                await db.execute(delete(FunnelEdge).where(FunnelEdge.from_step_id == delivery_step.id))
                db.add(FunnelEdge(funnel_version_id=version.id, from_step_id=delivery_step.id, to_step_id=word_id,
                    condition_json={"source_key": "message:timeout"}))
                delivery_step.config_json = {"messages": [{"text": "", "wait_for_answer": True}],
                    "auto_advance_enabled": True, "auto_advance_seconds": 60, "timeout_target_step_id": str(word_id)}
                state.current_step_id = delivery_step.id
                state.entered_step_at = datetime.now(timezone.utc)
                state.waiting_for_answer = True
                state.runtime_json = {"message_sequence": {"step_id": str(delivery_step.id), "message_index": 0}}
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "continued"
                assert state.current_step_id == word_id

                # A delayed free question also consumes its pending /start.
                state.current_step_id = word_id
                state.entered_step_at = datetime.now(timezone.utc)
                state.waiting_for_answer = False
                state.runtime_json = {"input_prompt_pending_step_id": str(word_id)}
                prompt_job = FunnelScheduledJob(chat_id=chat_id, funnel_state_id=state.id, funnel_id=funnel.id,
                    funnel_version_id=version.id, step_id=word_id, job_type="input_prompt", status="running",
                    run_at=datetime.now(timezone.utc) + timedelta(seconds=30))
                db.add(prompt_job); await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat_id, message_id=uuid4()) == "engagement_pending"
                await runtime.process_scheduled_job(prompt_job)
                assert state.current_step_id == phone_id and state.waiting_for_answer
                assert lead.phone == "+998909876543" and lead.age == 33

                # Signals never leak to a later visit, reset, or manager pause.
                state.current_step_id = word_id
                state.entered_step_at = datetime.now(timezone.utc)
                state.waiting_for_answer = True
                old = runtime._start_engagement_marker(state, uuid4())
                state.entered_step_at += timedelta(seconds=1)
                state.runtime_json = {"pending_start_engagement": old}
                await db.flush()
                word_step = await db.get(FunnelStep, word_id)
                assert await runtime._consume_pending_start_engagement(chat_id=chat_id, step=word_step) is None
                assert state.current_step_id == word_id and "pending_start_engagement" not in state.runtime_json
                pending = runtime._start_engagement_marker(state, uuid4())
                state.runtime_json = {"pending_start_engagement": pending}
                state.is_paused = True
                await db.flush()
                assert await runtime._consume_pending_start_engagement(chat_id=chat_id, step=word_step) is None
                assert state.current_step_id == word_id and state.is_paused
                assert "pending_start_engagement" not in runtime._runtime_for_manager_resume(state.runtime_json, preserve_answers=True)
                await db.rollback()
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
