"""Analysis-only schemas, offline routing and real PostgreSQL/Redis execution."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, Bot, Chat, Lead, Message, Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelScheduledJob, FunnelStepLog
from app.models.lead_status import LeadStatus
from app.schemas.ai import AIAnalysisConfig, AIAnalysisPayload
from app.schemas.funnel import FunnelStepIn
from app.services.ai_analysis_fallback_service import analyse_offline, citizenship_codes, country_aliases
from app.services.ai_analysis_execution_service import analysis_config, analysis_value_fits_field, offline_outcome
from app.services.ai_gateway_service import AIGatewayError, AIGatewayService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.ai_delivery_state_service import AIDeliveryStateService
from app.services.funnel_block_registry import FunnelBlockRegistry


@pytest.mark.skipif(not os.getenv("CRM_TEST_REDIS_URL"), reason="Disposable Redis required")
def test_analysis_provider_outage_circuit_is_scoped_and_does_not_trip_on_bad_output():
    async def run():
        from types import SimpleNamespace
        from redis.asyncio import Redis
        from app.services.ai_analysis_provider_guard import circuit_key, provider_on_cooldown, note_provider_error
        connection = SimpleNamespace(id=uuid4(), credential_fingerprint="version-one", base_url="https://provider.example")
        changed = SimpleNamespace(id=connection.id, credential_fingerprint="version-two", base_url=connection.base_url)
        async with Redis.from_url(os.environ["CRM_TEST_REDIS_URL"]) as redis:
            try:
                assert not await provider_on_cooldown(connection, "model")
                await note_provider_error(connection, "model", AIGatewayError("bad json", code="invalid_structured_output"))
                assert not await provider_on_cooldown(connection, "model")
                await note_provider_error(connection, "model", AIGatewayError("unavailable", code="provider_http_error", status_code=503))
                assert await provider_on_cooldown(connection, "model")
                assert not await provider_on_cooldown(changed, "model")
                assert not await provider_on_cooldown(connection, "other-model")
                assert 0 < await redis.ttl(circuit_key(connection, "model")) <= 30
            finally:
                await redis.delete(circuit_key(connection, "model"))
    asyncio.run(run())


@pytest.mark.parametrize("answer,expected", [
    ("рф", ["RU"]), ("Россия", ["RU"]), ("гражданин России", ["RU"]),
    ("🇷🇺", ["RU"]), ("🇺🇿", ["UZ"]), ("рассия", ["RU"]), ("росия", ["RU"]),
    ("Узбекистан", ["UZ"]), ("узб", ["UZ"]), ("O‘zbekiston", ["UZ"]), ("O'zbekiston fuqarosiman", ["UZ"]),
    ("узбекский паспорт", ["UZ"]), ("не РФ, паспорт Узбекистана", ["UZ"]),
    ("живу в РФ, паспорт UZ", ["UZ"]), ("México", ["MX"]), ("colombiano", ["CO"]),
    ("Россия и Казахстан", ["KZ", "RU"]), ("no", []), ("да", []), ("не РФ", []),
    ("гражданства РФ нет", []), ("живу в Москве", []), ("я из России", []), ("русский", []),
    ("hello and welcome", []), ("🙃", []), ("живу в 🇷🇺", []),
    ("нерф", []), ("нероссия", []), ("нерассия", []), ("notrussia", []),
    ("Rossiya emas", []), ("O'zbekiston yo'q", []), ("❌ 🇷🇺", []), ("Россия ❌", []),
    ("Непал", ["NP"]),
    ("гражданство РФ неимею", []), ("негражданин РФ", []), ("sin pasaporte de Perú", []),
])
def test_citizenship_fallback_is_conservative(answer, expected):
    assert citizenship_codes(answer) == expected


def test_country_base_and_analysis_payload_are_complete_and_separate_from_replies():
    known, aliases = country_aliases()
    assert len(known) == 249 and aliases["ru"] == "RU" and aliases["uz"] == "UZ"
    result = AIGatewayService._parse_response('{"next_route_key":"ru","normalized_answer":"RU","evidence":"Россия","extracted_data":{}}', analysis=True)
    assert isinstance(result, AIAnalysisPayload)
    with pytest.raises(AIGatewayError):
        AIGatewayService._parse_response('{"next_route_key":"ru","messages":["hello"]}', analysis=True)
    with pytest.raises(AIGatewayError):
        AIGatewayService._parse_response('{"next_route_key":"ru","extracted_data":{}}')
    from app.services.ai_response_execution_service import AIResponseExecutionService
    assert AIResponseExecutionService._history_messages([], max_context_chars=12000, continuation_prompt=False) == []
    AIResponseExecutionService._validate_model_payload(result, route_keys={"ru", "fallback"}, output_fields=[], analysis_answer="У меня гражданство Россия")
    with pytest.raises(AIGatewayError):
        AIResponseExecutionService._validate_model_payload(result, route_keys={"ru", "fallback"}, output_fields=[], analysis_answer="Живу в Москве")


def test_offline_routes_require_unique_matches_and_do_not_match_negative_substrings():
    config = {"fallback_type": "answers", "outcomes": [
        {"id": "yes", "aliases": ["да", "хочу"]}, {"id": "no", "aliases": ["нет"]}, {"id": "fallback"},
    ]}
    assert analyse_offline("Да 👍", config).next_route_key == "yes"
    assert analyse_offline("не хочу", config).next_route_key == "fallback"
    config["outcomes"][1]["aliases"].append("да")
    assert analyse_offline("да", config).next_route_key == "fallback"
    config = {"fallback_type": "citizenship", "outcomes": [
        {"id": "ru", "country_codes": ["RU"]}, {"id": "other", "country_match": "other"}, {"id": "fallback"},
    ]}
    assert analyse_offline("Узбекистан", config).next_route_key == "other"
    assert analyse_offline("Россия и Казахстан", config).next_route_key == "fallback"
    assert analyse_offline("не РФ", config).next_route_key == "fallback"
    config["outcomes"].append({"id": "not_ru", "aliases": ["не РФ", "нет"], "save_answer": False})
    refusal = analyse_offline("не РФ", config)
    assert refusal.next_route_key == "not_ru" and refusal.normalized_answer is None


def test_new_settings_are_opt_in_validated_and_required_outputs_are_checked():
    old = FunnelStepIn(key="q", title="Q", step_type="input", block_type="generic_input", config_json={"prompt": "Q?"})
    assert analysis_config(old) is None
    disabled = {"enabled": False, "outcomes": []}
    assert analysis_config(FunnelStepIn(key="q", title="Q", step_type="input", block_type="generic_input", config_json={"ai_analysis": disabled})) is None
    with pytest.raises(ValidationError):
        AIAnalysisConfig.model_validate({"enabled": True, "step_goal": "analyse", "outcomes": [{"id": "route", "label": "Route"}]})
    with pytest.raises(ValidationError):
        AIAnalysisConfig.model_validate({"outcomes": [{"id": "route", "label": "Route", "country_codes": ["XX"]}]})
    registry = FunnelBlockRegistry()
    assert registry.is_known("integration", "ai_analysis")
    config = {"step_goal": "analyse", "outcomes": [{"id": "ok", "label": "OK", "instruction": "Agrees"}, {"id": "fallback", "label": "Unknown"}]}
    assert any("подключите" in error for error in registry.validate_block("integration", "ai_analysis", config))
    assert analysis_value_fits_field("age", "18")
    assert not analysis_value_fits_field("age", "1000")
    assert not analysis_value_fits_field("age", "18.5")
    assert not analysis_value_fits_field("country", "x" * 101)
    assert not analysis_value_fits_field("phone", "123")
    assert not analysis_value_fits_field("has_card", "maybe")


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL") or not os.getenv("CRM_TEST_REDIS_URL"), reason="Disposable PostgreSQL and Redis required")
def test_analysis_jobs_route_without_sending_replies_and_ignore_obsolete_answers():
    async def run():
        schema = "analysis_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                now = datetime.now(timezone.utc)
                project, status = Project(name="Analysis", slug="analysis"), LeadStatus(name="New", code="new")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="No transport credentials")
                db.add(bot); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Analysis")
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush()
                question = FunnelStep(funnel_version_id=version.id, key="q", title="Citizenship", step_type="input", block_type="generic_input")
                good = FunnelStep(funnel_version_id=version.id, key="good", title="Good", step_type="finish", block_type="generic_finish")
                unknown = FunnelStep(funnel_version_id=version.id, key="unknown", title="Review", step_type="operator", block_type="manager_review")
                standalone = FunnelStep(funnel_version_id=version.id, key="analysis", title="Analysis", step_type="integration", block_type="ai_analysis")
                db.add_all([question, good, unknown, standalone]); await db.flush()
                config = {"enabled": True, "step_goal": "Classify citizenship", "fallback_type": "citizenship", "outcomes": [
                    {"id": "ru", "label": "RU", "instruction": "Russian citizenship", "country_codes": ["RU"], "target_step_id": str(good.id)},
                    {"id": "other", "label": "Other", "country_match": "other", "target_step_id": str(good.id)},
                    {"id": "fallback", "label": "Unknown", "target_step_id": str(unknown.id)},
                ]}
                question.config_json = {"prompt": "Citizenship?", "answer_type": "text", "custom_field_key": "citizenship", "ai_analysis": config}
                standalone.config_json = config
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="123", external_user_id="123", unanswered_push_count=2)
                db.add(chat); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, country="KZ", custom_fields={"kept": "value"})
                state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=question.id, entered_step_at=now, waiting_for_answer=True, runtime_json={})
                db.add_all([lead, state]); await db.flush()
                timer = FunnelScheduledJob(chat_id=chat.id, funnel_state_id=state.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    step_id=question.id, job_type="input_timeout", status="pending", run_at=now + timedelta(minutes=5))
                raw = Message(chat_id=chat.id, sender_type="user", message_type="text", body="не РФ")
                db.add_all([timer, raw]); await db.commit()
                runtime = FunnelRuntimeService(db)
                assert await runtime.process_incoming_message(chat_id=chat.id, text="не РФ", message_type="text")
                await db.commit()
                first = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis"))
                await db.refresh(state); await db.refresh(timer)
                assert not state.waiting_for_answer and timer.status == "cancelled" and state.entered_step_at == now
                assert await runtime.process_repeated_start(chat_id=chat.id) == "data_answer_required"
                assert await runtime.process_incoming_message(chat_id=chat.id, text="паспорт UZ", message_type="text")
                await db.commit()
                newest = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis", FunnelScheduledJob.status == "pending"))
                assert newest.id != first.id
                await runtime.process_scheduled_job(first)
                await db.refresh(state)
                assert state.current_step_id == question.id
                # No AI project settings: the actual production service uses the offline database.
                await runtime.process_scheduled_job(newest)
                await db.refresh(lead); await db.refresh(chat); await db.refresh(state); await db.refresh(raw)
                assert state.current_step_id == good.id and state.runtime_json["last_analysis"]["source"] == "dictionary"
                assert lead.custom_fields["citizenship"] == "UZ" and lead.custom_fields["kept"] == "value" and lead.country == "KZ"
                assert raw.body == "не РФ" and chat.unanswered_push_count == 2
                assert await db.scalar(select(func.count()).select_from(Message).where(Message.sender_type == "bot")) == 0
                assert await db.scalar(select(func.count()).select_from(FunnelStepLog).where(FunnelStepLog.event_type == "answered")) == 1
                # Re-running the old job cannot apply another decision or generate a second provider call.
                await runtime.process_scheduled_job(newest)
                assert await db.scalar(select(func.count()).select_from(FunnelStepLog).where(FunnelStepLog.event_type == "answered")) == 1
                # Recover a billable call interruption through offline routing, never a blind retry.
                state.current_step_id, state.entered_step_at, state.completed_at = standalone.id, now + timedelta(seconds=1), None
                state.runtime_json = {}
                await db.flush()
                await runtime._queue_ai_analysis(chat_id=chat.id, step=standalone, answer="Россия")
                await db.commit()
                recovery = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis", FunnelScheduledJob.step_id == standalone.id, FunnelScheduledJob.status == "pending"))
                delivery = AIDeliveryStateService(db)
                execution_id, marker = await delivery.begin(chat.id, standalone, recovery.id)
                marker["generation_started"] = True
                state = await delivery.current(chat.id, standalone.id, execution_id)
                delivery.write(state, marker); await db.commit()
                await runtime.process_scheduled_job(recovery)
                await db.refresh(state)
                assert state.current_step_id == good.id and state.runtime_json["last_analysis"]["error_code"] == "analysis_generation_interrupted"
                # Unclear citizenship must not overwrite the lead card.
                state.current_step_id, state.entered_step_at, state.completed_at = question.id, now + timedelta(seconds=2), None
                state.runtime_json = {}; state.waiting_for_answer = True
                await db.flush()
                await runtime.process_incoming_message(chat_id=chat.id, text="живу в Москве", message_type="text")
                await db.commit()
                unclear = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis", FunnelScheduledJob.step_id == question.id, FunnelScheduledJob.status == "pending"))
                await runtime.process_scheduled_job(unclear)
                await db.refresh(state); await db.refresh(lead)
                assert state.current_step_id == unknown.id and lead.custom_fields["citizenship"] == "UZ"
                # A durable, already-produced AI analysis resumes without delivery or provider access.
                state.current_step_id, state.entered_step_at, state.completed_at = question.id, now + timedelta(seconds=3), None
                state.runtime_json = {}; state.waiting_for_answer = True
                await db.flush()
                await runtime.process_incoming_message(chat_id=chat.id, text="Россия", message_type="text")
                await db.commit()
                ready = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis", FunnelScheduledJob.step_id == question.id, FunnelScheduledJob.status == "pending"))
                execution_id, marker = await delivery.begin(chat.id, question, ready.id)
                outcome = offline_outcome("Россия", config, error_code="fixture", error_message="persisted result")
                marker["outcome"] = {**asdict(outcome), "source": "ai", "used_fallback": False, "error_code": None}
                state = await delivery.current(chat.id, question.id, execution_id)
                delivery.write(state, marker); await db.commit()
                state.is_paused = True; await db.commit()
                await runtime.process_scheduled_job(ready)
                await db.refresh(state)
                assert state.current_step_id == question.id
                state.is_paused = False; await db.commit()
                await runtime.process_scheduled_job(ready)
                await db.refresh(state); await db.refresh(lead)
                assert state.runtime_json["last_analysis"]["source"] == "ai" and lead.custom_fields["citizenship"] == "RU"
                # Refusals are meaningful routes without replacing a phone with refusal text.
                question.config_json = {"prompt": "Phone?", "answer_type": "phone", "save_to": "phone", "ai_analysis": {
                    "enabled": True, "step_goal": "Detect refusal", "fallback_type": "answers", "outcomes": [
                        {"id": "refusal", "label": "Refusal", "instruction": "Refuses phone", "save_answer": False,
                         "aliases": ["не дам"], "target_step_id": str(good.id)},
                        {"id": "fallback", "label": "Unknown", "target_step_id": str(unknown.id)},
                    ]}}
                lead.phone = "+998901234567"
                state.current_step_id, state.entered_step_at, state.completed_at = question.id, now + timedelta(seconds=4), None
                state.runtime_json = {}; state.waiting_for_answer = True
                await db.flush()
                await runtime.process_incoming_message(chat_id=chat.id, text="не дам", message_type="text")
                await db.commit()
                refusal_job = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis",
                    FunnelScheduledJob.step_id == question.id, FunnelScheduledJob.status == "pending"))
                await runtime.process_scheduled_job(refusal_job)
                await db.refresh(state); await db.refresh(lead)
                assert state.current_step_id == good.id and lead.phone == "+998901234567"
                assert state.runtime_json["last_analysis"]["route_key"] == "refusal"
                # Never classify a clipped answer after losing negation or other context.
                state.current_step_id, state.entered_step_at, state.completed_at = question.id, now + timedelta(seconds=5), None
                state.runtime_json = {}; state.waiting_for_answer = True
                await db.flush()
                await runtime.process_incoming_message(chat_id=chat.id, text="не " + "Россия " * 3000, message_type="text")
                await db.commit()
                oversized = await db.scalar(select(FunnelScheduledJob).where(FunnelScheduledJob.job_type == "ai_analysis",
                    FunnelScheduledJob.step_id == question.id, FunnelScheduledJob.status == "pending"))
                await runtime.process_scheduled_job(oversized)
                await db.refresh(state); await db.refresh(lead)
                assert state.current_step_id == unknown.id and state.runtime_json["last_analysis"]["error_code"] == "analysis_input_too_long"
                assert lead.phone == "+998901234567"
                draft = FunnelVersion(funnel_id=funnel.id, version_number=2, status="draft")
                db.add(draft); await db.flush()
                await runtime.repo.clone_graph(version.id, draft.id)
                cloned = await runtime.repo.list_steps(draft.id)
                cloned_question = next(step for step in cloned if step.key == "q")
                cloned_good = next(step for step in cloned if step.key == "good")
                assert cloned_question.config_json["ai_analysis"]["outcomes"][0]["target_step_id"] == str(cloned_good.id)
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
