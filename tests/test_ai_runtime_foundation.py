from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.core.config import settings
from app.schemas.ai import AIProjectSettingsOut, AIResponsePayload
from app.services.ai_credential_service import AICredentialService
from app.services.ai_gateway_service import (
    AIGatewayError,
    AIGatewayResult,
    AIGatewayService,
    AIProviderSnapshot,
)
from app.services.ai_response_execution_service import AIResponseExecutionService
from app.services.funnel_block_registry import FunnelBlockRegistry


def test_ai_credentials_are_encrypted_and_fingerprinted_by_key_version() -> None:
    original = settings.AI_CREDENTIAL_ENCRYPTION_KEY
    settings.AI_CREDENTIAL_ENCRYPTION_KEY = "test-only-stable-ai-encryption-key"
    try:
        service = AICredentialService()
        plaintext = "provider-secret-key-1234"
        encrypted = service.encrypt(plaintext)

        assert plaintext not in encrypted
        assert service.decrypt(encrypted) == plaintext
        assert service.last_four(plaintext) == "1234"
        assert service.fingerprint(plaintext) == service.fingerprint(plaintext)
        assert service.fingerprint(plaintext) != service.fingerprint(
            "another-provider-secret-key-1234"
        )
    finally:
        settings.AI_CREDENTIAL_ENCRYPTION_KEY = original


def test_ai_project_settings_are_opt_in_by_default() -> None:
    payload = AIProjectSettingsOut(project_id=uuid4())

    assert payload.is_enabled is False
    assert payload.primary_connection_id is None
    assert payload.fallback_connection_id is None


def test_gateway_parses_structured_json_and_calculates_configured_price() -> None:
    response = AIGatewayService._parse_response(
        """
        ```json
        {
          "messages": ["Понял вас.", "Уточните удобное время."],
          "extracted_data": {"city": "Томск"},
          "next_route_key": "continue"
        }
        ```
        """
    )
    cost = AIGatewayService.estimate_cost(
        pricing_json={
            "live-model-id": {
                "input_usd_per_million": "1.50",
                "output_usd_per_million": "6.00",
            }
        },
        model="live-model-id",
        prompt_tokens=1_000,
        completion_tokens=500,
    )

    assert response.messages == ["Понял вас.", "Уточните удобное время."]
    assert response.extracted_data == {"city": "Томск"}
    assert response.next_route_key == "continue"
    assert cost == Decimal("0.0045")


def test_invalid_structured_output_keeps_billable_usage() -> None:
    service = AIGatewayService()
    service._call_openai_compatible = AsyncMock(
        return_value=(
            {
                "choices": [{"message": {"content": "not-json"}}],
                "usage": {
                    "prompt_tokens": 1_000,
                    "completion_tokens": 500,
                    "total_tokens": 1_500,
                },
            },
            "request-1",
        )
    )
    connection = AIProviderSnapshot(
        id=uuid4(),
        provider="test",
        api_style="openai_compatible",
        base_url="https://provider.example.test/v1",
        api_key="secret",
        credential_fingerprint="fingerprint",
        api_key_last_four="1234",
        request_timeout_seconds=20,
        supports_json_mode=True,
        pricing_json={
            "live-model-id": {
                "input_usd_per_million": "1.50",
                "output_usd_per_million": "6.00",
            }
        },
    )

    try:
        asyncio.run(
            service.execute(
                connection=connection,
                model="live-model-id",
                system_prompt="Return JSON",
                messages=[{"role": "user", "content": "Hello"}],
                temperature=0,
                max_output_tokens=100,
            )
        )
    except AIGatewayError as error:
        assert error.code == "invalid_structured_output"
        assert error.total_tokens == 1_500
        assert error.estimated_cost_usd == Decimal("0.0045")
        assert error.provider_request_id == "request-1"
    else:
        raise AssertionError("Invalid structured output must fail")


def test_ai_block_validation_does_not_change_legacy_integrations() -> None:
    registry = FunnelBlockRegistry()
    ai_errors = registry.validate_block(
        "integration",
        "ai_response",
        {
            "step_goal": "Ответить и определить интерес клиента",
            "outcomes": [
                {"id": "continue", "label": "Продолжить"},
                {"id": "fallback", "label": "Передать менеджеру"},
            ],
            "output_fields": [
                {
                    "response_key": "interest",
                    "lead_field_key": "interest",
                    "value_type": "text",
                }
            ],
        },
    )
    legacy_errors = registry.validate_block(
        "integration",
        "generic_integration",
        {"integration_type": "webhook", "url": "https://crm.example.test/hook"},
    )

    assert ai_errors == []
    assert legacy_errors == []


def test_ai_block_requires_explicit_fallback_route() -> None:
    errors = FunnelBlockRegistry().validate_block(
        "integration",
        "ai_response",
        {
            "step_goal": "Ответить клиенту",
            "outcomes": [{"id": "continue", "label": "Продолжить"}],
        },
    )

    assert any("fallback" in error for error in errors)


class _OneReadStep:
    def __init__(self, step_id) -> None:
        self.config_json = {
            "step_goal": "Ответить клиенту",
            "outcomes": [
                {"id": "continue", "label": "Продолжить"},
                {"id": "fallback", "label": "Ошибка"},
            ],
        }
        self._step_id = step_id
        self.id_reads = 0

    @property
    def id(self):
        self.id_reads += 1
        if self.id_reads > 1:
            raise AssertionError("Funnel step ORM data was read after transaction commit")
        return self._step_id


def test_fallback_provider_does_not_reload_step_after_commit() -> None:
    project_id = uuid4()
    chat_id = uuid4()
    step_id = uuid4()
    primary_id = uuid4()
    fallback_id = uuid4()
    step = _OneReadStep(step_id)
    db = SimpleNamespace(
        in_transaction=MagicMock(return_value=True),
        commit=AsyncMock(),
    )
    service = AIResponseExecutionService.__new__(AIResponseExecutionService)
    service.db = db
    service.chat_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                project_id=project_id,
                external_user_id="100",
            )
        )
    )
    service.funnel_repo = SimpleNamespace(
        get_chat_funnel_state=AsyncMock(
            return_value=SimpleNamespace(
                funnel_id=uuid4(),
                funnel_version_id=uuid4(),
            )
        ),
        get_lead_by_chat=AsyncMock(
            return_value=SimpleNamespace(
                id=uuid4(),
                name="Анна",
                username="anna",
                phone=None,
                age=None,
                country=None,
                custom_fields={},
            )
        ),
        get_message_template_context=AsyncMock(return_value={}),
    )
    service.message_repo = SimpleNamespace(list_by_chat=AsyncMock(return_value=[]))
    service.project_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=SimpleNamespace(name="Проект"))
    )
    service.credentials = SimpleNamespace(decrypt=MagicMock(return_value="secret"))
    service.ai_repo = SimpleNamespace(
        get_project_settings=AsyncMock(
            return_value=SimpleNamespace(
                is_enabled=True,
                primary_connection_id=primary_id,
                primary_model="primary-live-model",
                fallback_connection_id=fallback_id,
                fallback_model="fallback-live-model",
                master_prompt="Отвечай кратко.",
                history_message_limit=20,
                max_context_chars=16_000,
                default_temperature=Decimal("0.4"),
                default_max_output_tokens=400,
                typing_delay_per_char_ms=30,
                min_delay_ms=500,
                max_delay_ms=3_500,
                daily_budget_usd=None,
                monthly_budget_usd=None,
            )
        ),
        get_connection=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    id=primary_id,
                    provider="primary",
                    api_style="openai_compatible",
                    base_url="https://primary.example.test/v1",
                    encrypted_api_key="encrypted",
                    credential_fingerprint="primary-fingerprint",
                    api_key_last_four="1111",
                    request_timeout_seconds=20,
                    supports_json_mode=True,
                    pricing_json={},
                ),
                SimpleNamespace(
                    id=fallback_id,
                    provider="fallback",
                    api_style="openai_compatible",
                    base_url="https://fallback.example.test/v1",
                    encrypted_api_key="encrypted",
                    credential_fingerprint="fallback-fingerprint",
                    api_key_last_four="2222",
                    request_timeout_seconds=20,
                    supports_json_mode=True,
                    pricing_json={},
                ),
            ]
        ),
        create_usage_log=AsyncMock(),
    )
    service.gateway = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                AIGatewayError(
                    "Primary provider is unavailable",
                    code="provider_network_error",
                    retriable=True,
                ),
                AIGatewayResult(
                    response=AIResponsePayload(
                        messages=["Ответ резервной модели"],
                        extracted_data={},
                        next_route_key="continue",
                    ),
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    estimated_cost_usd=None,
                    latency_ms=25,
                    provider_request_id="fallback-request",
                ),
            ]
        )
    )

    outcome = asyncio.run(service.execute(chat_id=chat_id, step=step))

    assert outcome.success is True
    assert outcome.used_fallback is True
    assert outcome.messages == ["Ответ резервной модели"]
    assert step.id_reads == 1
    assert service.ai_repo.create_usage_log.await_count == 2
