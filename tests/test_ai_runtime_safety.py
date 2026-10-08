"""Pure validation and real PostgreSQL tests; no provider or database mocks."""
import asyncio
import importlib.util
import json
import os
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.ai_provider_security import validate_provider_url, provider_request
from app.core.config import settings
from app.models import Base, Bot, Chat, Funnel, FunnelStep, FunnelVersion, Project
from app.models.ai import (
    AIBudgetReservation,
    AIProjectSettings,
    AIProviderConnection,
    AIUsageLog,
)
from app.models.funnel import ChatFunnelState
from app.repositories.ai_repository import AIRepository
from app.repositories.funnel_repository import FunnelRepository
from app.schemas.ai import AIProviderConnectionCreate, AIResponsePayload
from app.services.ai_budget_service import AIBudgetService
from app.services.ai_delivery_state_service import AIDeliveryStateService
from app.services.ai_gateway_service import (
    AIGatewayError,
    AIGatewayService,
    AIProviderSnapshot,
)
from app.services.ai_response_execution_service import (
    AIResponseExecutionOutcome,
    AIResponseExecutionService,
)
from app.services.funnel_runtime_service import FunnelRuntimeService


def snapshot(**changes):
    return AIProviderSnapshot(
        **{
            "id": uuid4(),
            "provider": "openai",
            "api_style": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "credential_fingerprint": None,
            "api_key_last_four": None,
            "request_timeout_seconds": 5,
            "supports_json_mode": True,
            "pricing_json": {},
            **changes,
        }
    )


@pytest.mark.parametrize(
    "value,value_type",
    [
        ([], "text"),
        ({}, "text"),
        (["x"], "number"),
        (True, "number"),
        ("NaN", "number"),
        ("Infinity", "number"),
        ("maybe", "boolean"),
        ("x" * 256, "text"),
    ],
)
def test_invalid_extracted_values_are_structured_errors(value, value_type):
    payload = AIResponsePayload(
        messages=["Hello"], extracted_data={"name": value}, next_route_key="continue"
    )
    with pytest.raises(AIGatewayError) as caught:
        AIResponseExecutionService._validate_model_payload(
            payload,
            route_keys={"continue"},
            output_fields=[
                {
                    "response_key": "name",
                    "lead_field_key": "name"
                    if value_type == "text"
                    else "custom_value",
                    "required": True,
                    "value_type": value_type,
                }
            ],
        )
    assert caught.value.code == "invalid_extracted_data"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_required_values(value):
    with pytest.raises(AIGatewayError, match="required"):
        AIResponseExecutionService._validate_model_payload(
            AIResponsePayload(
                messages=["Hello"],
                extracted_data={"x": value},
                next_route_key="continue",
            ),
            route_keys={"continue"},
            output_fields=[{"response_key": "x", "required": True}],
        )


def test_chunks_keep_all_text_and_respect_utf16_limit():
    for source in ("a" * 3000 + "\n\n" + "b" * 3000, "\U0001f600" * 4096):
        chunks = AIResponseExecutionService._telegram_chunks(source)
        assert "".join(chunks) == source
        assert len(chunks) == 2
        assert all(len(chunk.encode("utf-16-le")) // 2 <= 4096 for chunk in chunks)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",
        "https://127.0.0.1",
        "https://[::1]",
        "https://169.254.169.254",
        "https://localhost",
        "https://user:secret@api.openai.com",
        "https://api.openai.com?key=secret",
        "https://api.openai.com#secret",
        "https://api.openai.com:bad",
    ],
)
def test_unsafe_origins_rejected(url):
    with pytest.raises(ValueError):
        validate_provider_url(url)


def test_self_hosted_origin_must_be_explicit_and_exact():
    previous = settings.AI_TRUSTED_PROVIDER_ORIGINS
    settings.AI_TRUSTED_PROVIDER_ORIGINS = "http://127.0.0.1:11434"
    try:
        assert (
            validate_provider_url("http://127.0.0.1:11434/v1")
            == "http://127.0.0.1:11434/v1"
        )
        with pytest.raises(ValueError):
            validate_provider_url("http://127.0.0.1:11435/v1")
        with pytest.raises(ValueError):
            validate_provider_url("http://127.0.0.1:11434@other.example/v1")
    finally:
        settings.AI_TRUSTED_PROVIDER_ORIGINS = previous


def test_direct_lead_fields_use_database_types_even_for_old_ai_config():
    fields = AIResponseExecutionService._output_fields(
        {
            "output_fields": [
                {"response_key": "age", "lead_field_key": "age", "value_type": "text"},
                {
                    "response_key": "card",
                    "lead_field_key": "has_card",
                    "value_type": "text",
                },
                {
                    "response_key": "name",
                    "lead_field_key": "name",
                    "value_type": "number",
                },
            ]
        }
    )
    assert [item["value_type"] for item in fields] == ["number", "boolean", "text"]
    payload = AIResponsePayload(
        messages=["Hello"],
        extracted_data={"age": "27", "card": True, "name": "Arslan"},
        next_route_key="continue",
    )
    AIResponseExecutionService._validate_model_payload(
        payload, route_keys={"continue"}, output_fields=fields
    )


def test_private_dns_resolution_is_rejected_before_request():
    async def run():
        with pytest.raises(ValueError, match="non-public"):
            await provider_request("GET", "https://127.0.0.1.nip.io", timeout=5)

    # This case deliberately exercises real DNS only when explicitly requested.
    if not os.getenv("AI_SAFETY_TEST_NETWORK"):
        pytest.skip("Set AI_SAFETY_TEST_NETWORK=1 for real DNS verification")
    asyncio.run(run())


def test_model_capabilities_have_legacy_defaults_and_explicit_overrides():
    assert (
        AIGatewayService.model_options(snapshot(), "gpt-4o")["token_parameter"]
        == "max_tokens"
    )
    for model in ("o3", "o4-mini", "gpt-5", "gpt-5.2"):
        options = AIGatewayService.model_options(snapshot(), model)
        assert options["token_parameter"] == "max_completion_tokens"
        assert options["supports_temperature"] is False
    custom = snapshot(
        provider="custom",
        model_options_json={
            "new-model": {
                "token_parameter": "max_completion_tokens",
                "supports_temperature": False,
                "supports_json_mode": False,
            }
        },
    )
    assert (
        AIGatewayService.model_options(custom, "new-model")
        == custom.model_options_json["new-model"]
    )
    created = AIProviderConnectionCreate(
        name="Provider",
        provider="custom",
        api_key="key",
        base_url="https://example.com/v1",
        model_options={" new-model ": {"supports_temperature": False}},
    )
    assert list(created.model_options) == ["new-model"]


def test_budget_requires_complete_finite_prices_and_usage():
    connection = snapshot(
        pricing_json={
            "model": {"input_usd_per_million": "1", "output_usd_per_million": "2"}
        }
    )
    reserve = AIBudgetService.request_reserve(
        connection, "model", "Hello", [{"content": "Hi"}], 100
    )
    assert reserve > Decimal("0.001")
    assert (
        AIGatewayService.estimate_cost(
            pricing_json=connection.pricing_json,
            model="model",
            prompt_tokens=None,
            completion_tokens=100,
        )
        is None
    )
    with pytest.raises(AIGatewayError, match="prices"):
        AIBudgetService.request_reserve(snapshot(), "model", "Hello", [], 100)


def test_postgresql_budget_concurrency_execution_markers_and_migration():
    url = os.getenv("AI_SAFETY_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set AI_SAFETY_TEST_DATABASE_URL for isolated real PostgreSQL tests"
        )

    async def run():
        schema = "ai_safety_" + uuid4().hex
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            url,
            connect_args={"server_settings": {"search_path": schema}},
            pool_size=10,
            max_overflow=10,
        )
        session = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with session() as db:
                project = Project(name="AI safety", slug="ai-safety")
                db.add(project)
                await db.flush()
                project_id = project.id
                db.add(
                    AIProjectSettings(
                        project_id=project_id,
                        is_enabled=True,
                        daily_budget_usd=Decimal("1"),
                    )
                )
                provider = AIProviderConnection(
                    name="Persisted provider",
                    provider="custom",
                    base_url="https://example.com/v1",
                    pricing_json={
                        "model": {
                            "input_usd_per_million": "1",
                            "output_usd_per_million": "2",
                        }
                    },
                    encrypted_api_key="persisted-ciphertext",
                )
                db.add(provider)
                await db.commit()
                provider_id = provider.id

            # Upgrade/downgrade operate on the previous schema and preserve old data.
            path = (
                Path(__file__).resolve().parents[1]
                / "alembic/versions/20261008_0080_ai_runtime_safety.py"
            )
            spec = importlib.util.spec_from_file_location("ai_safety_migration", path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            def roundtrip(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migration.downgrade()
                    assert "model_options_json" not in {
                        c["name"]
                        for c in inspect(connection).get_columns(
                            "ai_provider_connections"
                        )
                    }
                    assert (
                        "ai_budget_reservations"
                        not in inspect(connection).get_table_names()
                    )
                    migration.upgrade()

            async with engine.begin() as conn:
                await conn.run_sync(roundtrip)
            async with session() as db:
                provider = await db.get(AIProviderConnection, provider_id)
                assert provider.encrypted_api_key == "persisted-ciphertext"
                assert provider.model_options_json == {}
                assert provider.pricing_json["model"]["input_usd_per_million"] == "1"

            async def reserve():
                async with session() as db:
                    try:
                        reservation = await AIBudgetService(db).reserve(
                            project_id, Decimal("0.6")
                        )
                        await db.commit()
                        return reservation.id
                    except AIGatewayError as exc:
                        assert exc.code == "ai_budget_exceeded"
                        await db.rollback()
                        return None

            results = await asyncio.gather(*(reserve() for _ in range(12)))
            assert sum(value is not None for value in results) == 1
            async with session() as db:
                reservation = await db.get(
                    AIBudgetReservation, next(value for value in results if value)
                )
                assert await AIBudgetService(db).allocated(
                    project_id, reservation.created_at
                ) == Decimal("0.6")
                summary = await AIRepository(db).usage_summary(
                    project_id=project_id,
                    date_from=reservation.created_at - timedelta(seconds=1),
                    date_to=datetime.now(timezone.utc) + timedelta(seconds=1),
                )
                assert summary["reserved_cost_usd"] == Decimal("0.6")
                db.add(
                    AIUsageLog(
                        project_id=project_id,
                        provider="custom",
                        model="model",
                        status="success",
                        estimated_cost_usd=Decimal("0.1"),
                        created_at=reservation.created_at,
                    )
                )
                reservation.settled = True
                await db.commit()
            # Settled usage frees only the difference, including for fallback calls.
            assert (
                sum(
                    value is not None
                    for value in await asyncio.gather(*(reserve() for _ in range(4)))
                )
                == 1
            )

            async with session() as db:
                bot = Bot(project_id=project_id, name="Safety bot")
                db.add(bot)
                await db.flush()
                funnel = Funnel(
                    project_id=project_id, bot_id=bot.id, name="Safety funnel"
                )
                db.add(funnel)
                await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1)
                db.add(version)
                await db.flush()
                step = FunnelStep(
                    funnel_version_id=version.id,
                    key="ai",
                    title="AI",
                    step_type="integration",
                    block_type="ai_response",
                )
                db.add(step)
                chat = Chat(
                    project_id=project_id,
                    bot_id=bot.id,
                    external_chat_id="42",
                    external_user_id="42",
                )
                db.add(chat)
                await db.flush()
                state = ChatFunnelState(
                    chat_id=chat.id,
                    funnel_id=funnel.id,
                    funnel_version_id=version.id,
                    current_step_id=step.id,
                    entered_step_at=datetime.now(timezone.utc),
                    runtime_json={"legacy": "preserved"},
                )
                db.add(state)
                await db.commit()
                chat_id, step_id, job_id = chat.id, step.id, uuid4()
                delivery = AIDeliveryStateService(db)
                execution_id, marker = await delivery.begin(chat_id, step, job_id)
                assert await delivery.begin(chat_id, step, uuid4()) is None
                await db.commit()
                outcome = AIResponseExecutionOutcome(
                    True, ["Saved reply"], {}, "continue", False, None, None, 0, 0, 0
                )
                assert await delivery.save_outcome(
                    chat_id, step_id, execution_id, outcome
                )
                await db.commit()
                # A new database session resumes the saved response, no model call.
                async with session() as other:
                    recovered = await AIDeliveryStateService(other).begin(
                        chat_id, step, job_id
                    )
                    assert recovered[1]["outcome"]["messages"] == ["Saved reply"]
                    await other.commit()
                # Manager pause invalidates an in-flight result even after unpause.
                await FunnelRepository(db).set_chat_funnel_paused(
                    chat_id=chat_id, is_paused=True
                )
                await db.commit()
                await FunnelRepository(db).set_chat_funnel_paused(
                    chat_id=chat_id, is_paused=False
                )
                await db.commit()
                assert await delivery.current(chat_id, step_id, execution_id) is None
                assert state.runtime_json["legacy"] == "preserved"
                await db.commit()
                execution_id, _ = await delivery.begin(chat_id, step, uuid4())
                # Returning to the same step is a different visit.
                async with session() as other:
                    row = await other.get(ChatFunnelState, state.id)
                    row.entered_step_at += timedelta(seconds=1)
                    await other.commit()
                assert await delivery.current(chat_id, step_id, execution_id) is None
                await db.commit()
                # Fault injection into persisted delivery progress: recovery must
                # pause, not call either external provider or Telegram again.
                recovery_job = uuid4()
                execution_id, marker = await delivery.begin(chat_id, step, recovery_job)
                assert await delivery.save_outcome(
                    chat_id, step_id, execution_id, outcome
                )
                state = await delivery.current(chat_id, step_id, execution_id)
                marker = dict(state.runtime_json["ai_execution"])
                marker["inflight_index"] = 0
                delivery.write(state, marker)
                await db.commit()
                alerts_enabled = settings.OPERATIONAL_ALERTS_ENABLED
                settings.OPERATIONAL_ALERTS_ENABLED = False
                try:
                    await FunnelRuntimeService(db)._execute_ai_response_job(
                        chat_id=chat_id, step=step, job_id=recovery_job
                    )
                finally:
                    settings.OPERATIONAL_ALERTS_ENABLED = alerts_enabled
                await db.refresh(state)
                assert state.is_paused
                assert state.runtime_json["ai_execution"]["status"] == "uncertain"
                assert await db.scalar(text("SELECT COUNT(*) FROM messages")) == 0
                assert (
                    await db.scalar(
                        text(
                            "SELECT COUNT(*) FROM funnel_runtime_logs WHERE error_message LIKE 'ai_delivery_uncertain:%'"
                        )
                    )
                    == 1
                )
                await db.commit()
                state.is_paused = False
                state.entered_step_at += timedelta(seconds=1)
                await db.commit()
                interrupted_job = uuid4()
                execution_id, marker = await delivery.begin(
                    chat_id, step, interrupted_job
                )
                marker["generation_started"] = True
                delivery.write(state, marker)
                await db.commit()
                settings.OPERATIONAL_ALERTS_ENABLED = False
                try:
                    await FunnelRuntimeService(db)._execute_ai_response_job(
                        chat_id=chat_id, step=step, job_id=interrupted_job
                    )
                finally:
                    settings.OPERATIONAL_ALERTS_ENABLED = alerts_enabled
                await db.refresh(state)
                assert state.is_paused
                assert (
                    state.runtime_json["ai_execution"]["error"]
                    == "generation interrupted"
                )
                state.is_paused = False
                state.entered_step_at += timedelta(seconds=1)
                legacy_messages = ["Legacy reply"]
                marker = {
                    "id": str(uuid4()),
                    "state_id": str(state.id),
                    "step_id": str(step_id),
                    "version_id": str(state.funnel_version_id),
                    "visit": delivery.visit(state),
                    "next_index": 0,
                    "inflight_index": 0,
                    "status": "delivering",
                    "legacy_delivery_key": sha256(
                        json.dumps(
                            [legacy_messages, "continue"], ensure_ascii=True
                        ).encode()
                    ).hexdigest(),
                }
                delivery.write(state, marker)
                await db.commit()
                settings.OPERATIONAL_ALERTS_ENABLED = False
                try:
                    await FunnelRuntimeService(db)._deliver_ai_response_and_continue(
                        chat_id=chat_id,
                        step=step,
                        messages=legacy_messages,
                        route_key="continue",
                        start_index=0,
                        typing_delay_per_char_ms=0,
                        min_delay_ms=0,
                        max_delay_ms=0,
                    )
                finally:
                    settings.OPERATIONAL_ALERTS_ENABLED = alerts_enabled
                await db.refresh(state)
                assert state.is_paused
                assert state.runtime_json["ai_execution"]["id"] == marker["id"]
                assert await db.scalar(text("SELECT COUNT(*) FROM messages")) == 0
                await db.commit()
        finally:
            await engine.dispose()
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()

    asyncio.run(run())
