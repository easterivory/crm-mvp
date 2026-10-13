"""Versioned reminder policy and delivery plans, without transport mocks."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Message, Project
from app.models.broadcast import BroadcastUpload
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelScheduledJob, FunnelStepLog
from app.models.lead_status import LeadStatus
from app.schemas.funnel import FunnelStepIn
from app.services.funnel_runtime_service import FunnelRuntimeService


def test_reminder_settings_are_opt_in_and_do_not_rewrite_legacy_configs():
    original = {"messages": [{"text": "Continue?", "wait_for_answer": True}]}
    step = FunnelStepIn(key="message", title="Message", step_type="message", block_type="generic_message", config_json=original)
    assert step.config_json == original
    assert "repeat_start_mode" not in step.model_dump()["config_json"]


@pytest.mark.parametrize("config", [
    {"repeat_start_mode": []}, {"repeat_start_mode": "reset"}, {"repeat_start_mode": None},
    {"repeat_start_defaults": {"mode": "reset"}}, {"repeat_start_defaults": {"mode": "remind", "text": "x" * 4001}},
])
def test_invalid_reminder_config_is_rejected(config):
    with pytest.raises(ValidationError):
        FunnelStepIn(key="start", title="Start", step_type="trigger", block_type="generic_trigger", config_json=config)


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_reminders_keep_visit_data_timers_and_callback_routes_and_clone_settings():
    async def run():
        schema = "reminders_" + uuid4().hex
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
                now = datetime.now(timezone.utc)
                project = Project(name="Reminder", slug="reminder", project_format="gambling")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="No transport credentials")
                db.add(bot); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Reminder")
                db.add(funnel); await db.flush()
                old = FunnelVersion(funnel_id=funnel.id, version_number=1, status="archived")
                version = FunnelVersion(funnel_id=funnel.id, version_number=2, status="published")
                db.add_all([old, version]); await db.flush()
                trigger = FunnelStep(funnel_version_id=version.id, key="start", title="Start", step_type="trigger", block_type="generic_trigger",
                    config_json={"repeat_start_defaults": {"mode": "remind", "text": "Continue together"}})
                old_trigger = FunnelStep(funnel_version_id=old.id, key="start", title="Start", step_type="trigger", block_type="generic_trigger")
                question = FunnelStep(funnel_version_id=version.id, key="age", title="Age", step_type="input", block_type="generic_input",
                    config_json={"prompt": "Age?", "field_key": "age", "answer_type": "number"})
                photo = FunnelStep(funnel_version_id=version.id, key="photo", title="Photo", step_type="message", block_type="generic_message")
                db.add_all([trigger, old_trigger, question, photo]); await db.flush()
                upload = BroadcastUpload(project_id=project.id, file_name="photo.jpg", mime_type="image/jpeg", file_size=100,
                    media_type="photo", storage_path="not-retained.jpg", expires_at=now - timedelta(days=1))
                db.add(upload); await db.flush()
                photo.config_json = {"messages": [
                    {"text": "Earlier"},
                    {"type": "photo", "text": "Current caption", "media": {"source": "upload", "upload_id": str(upload.id), "media_type": "photo"},
                     "buttons": [{"label": "Answer", "value": "yes", "type": "callback", "target_step_id": str(question.id)}]},
                    {"text": "Later, do not replay"},
                ]}
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="12345", external_user_id="12345", unanswered_push_count=3)
                db.add(chat); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, age=40, phone="+998901234567", custom_fields={"budget": 10})
                state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=question.id, entered_step_at=now - timedelta(minutes=5), waiting_for_answer=True,
                    runtime_json={"last_answer": "kept", "confidence_reask_count": 0, "push_rules_sent": {"kept": "visit"}})
                db.add_all([lead, state]); await db.flush()
                job = FunnelScheduledJob(chat_id=chat.id, funnel_state_id=state.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    step_id=question.id, job_type="input_timeout", status="pending", run_at=now + timedelta(minutes=10))
                delivered = Message(chat_id=chat.id, sender_type="bot", message_type="photo", caption="Current caption",
                    telegram_file_id="qa-retained-file-id", raw_payload_json={"broadcast_upload_id": str(upload.id)})
                db.add_all([job, delivered]); await db.commit()
                runtime = FunnelRuntimeService(db)
                assert await runtime._repeated_start_settings(old.id, question) == ("continue", "")
                assert await runtime._repeated_start_settings(version.id, question) == ("remind", "Continue together")
                question.config_json = {**question.config_json, "repeat_start_mode": "continue"}
                await db.flush()
                assert await runtime._repeated_start_settings(version.id, question) == ("continue", "Continue together")
                trigger.config_json = {"repeat_start_defaults": {"mode": "continue", "text": "Continue together"}}
                question.config_json = {**question.config_json, "repeat_start_mode": "remind"}
                await db.flush()
                assert await runtime._repeated_start_settings(version.id, question) == ("remind", "Continue together")
                question.config_json = {**question.config_json, "repeat_start_mode": "inherit"}
                trigger.config_json = {"repeat_start_defaults": {"mode": "remind", "text": ""}}
                await db.flush()
                entered, original_run_at = state.entered_step_at, job.run_at
                request_id = uuid4()
                # A real credential-less transport fails without sending or progressing.
                with pytest.raises(HTTPException):
                    await runtime.process_repeated_start(chat_id=chat.id, message_id=request_id)
                assert await runtime.process_repeated_start(chat_id=chat.id, message_id=request_id) == "already_processed"
                assert await runtime.process_repeated_start(chat_id=chat.id, message_id=uuid4()) == "reminder_cooldown"
                await db.refresh(state); await db.refresh(lead); await db.refresh(chat); await db.refresh(job)
                assert state.current_step_id == question.id and state.entered_step_at == entered and state.waiting_for_answer
                assert lead.age == 40 and lead.phone == "+998901234567" and lead.custom_fields == {"budget": 10}
                assert chat.unanswered_push_count == 3 and state.runtime_json["last_answer"] == "kept"
                assert state.runtime_json["confidence_reask_count"] == 0 and state.runtime_json["push_rules_sent"] == {"kept": "visit"}
                assert job.status == "pending" and job.run_at == original_run_at
                assert await db.scalar(select(func.count()).select_from(FunnelStepLog)) == 0
                # Mandatory input can queue a reminder without consuming an answer.
                state.runtime_json = {**state.runtime_json, "input_prompt_pending_step_id": str(question.id)}
                state.runtime_json.pop("last_start_reminder", None)
                state.waiting_for_answer = False
                prompt = FunnelScheduledJob(chat_id=chat.id, funnel_state_id=state.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    step_id=question.id, job_type="input_prompt", status="pending", run_at=now + timedelta(seconds=30))
                db.add(prompt); await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id, message_id=uuid4()) == "engagement_pending"
                state.waiting_for_answer = True
                state.runtime_json = {key: value for key, value in state.runtime_json.items() if key != "input_prompt_pending_step_id"}
                await db.flush()
                assert await runtime._consume_pending_start_engagement(chat_id=chat.id, step=question) == "reminded"
                await db.refresh(state); await db.refresh(job)
                assert state.entered_step_at == entered and job.run_at == original_run_at and job.status == "pending"
                state.is_paused = True
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id) == "paused"
                state.is_paused = False
                state.completed_at = now
                await db.flush()
                assert await runtime.process_repeated_start(chat_id=chat.id) == "inactive"
                state.completed_at = None
                state.current_step_id = photo.id
                state.runtime_json = {"message_sequence": {"step_id": str(photo.id), "message_index": 1}}
                await db.flush()
                item = runtime._message_sequence(photo)[1]
                markup = runtime._reply_markup_for_buttons(step=photo, buttons=runtime._buttons_from_message_item(item), message_index=1,
                    button_mode=runtime._message_item_button_mode(item))
                delivery = await runtime._message_item_delivery(chat_id=chat.id, step=photo, item=item, reply_markup=markup, reuse_upload_delivery=True)
                assert delivery["text"] == "Current caption" and delivery["message_type"] == "photo"
                assert delivery["broadcast_upload_id"] is None and delivery["telegram_file_id"] == "qa-retained-file-id"
                callback = delivery["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
                assert ":1:" in callback
                question.config_json = {**question.config_json, "prompt": " "}
                await db.flush()
                await runtime.process_incoming_button(chat_id=chat.id, callback_data=callback)
                await db.refresh(state)
                assert state.current_step_id == question.id
                draft = FunnelVersion(funnel_id=funnel.id, version_number=3, status="draft")
                db.add(draft); await db.flush()
                await runtime.repo.clone_graph(version.id, draft.id)
                copied = await runtime.repo.list_steps(draft.id)
                copied_start = next(step for step in copied if step.key == "start")
                copied_question = next(step for step in copied if step.key == "age")
                assert copied_start.config_json["repeat_start_defaults"] == trigger.config_json["repeat_start_defaults"]
                assert copied_question.config_json["repeat_start_mode"] == "inherit"
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
