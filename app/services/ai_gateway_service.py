from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.schemas.ai import AIResponsePayload
from app.core.ai_provider_security import provider_request

logger = logging.getLogger(__name__)

JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)


class AIGatewayError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int | None = None,
        retriable: bool = False,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: Decimal | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.retriable = retriable
        self.latency_ms = latency_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.estimated_cost_usd = estimated_cost_usd
        self.provider_request_id = provider_request_id
        super().__init__(message[:1000])


@dataclass(frozen=True)
class AIProviderSnapshot:
    id: Any
    provider: str
    api_style: str
    base_url: str
    api_key: str
    credential_fingerprint: str | None
    api_key_last_four: str | None
    request_timeout_seconds: int
    supports_json_mode: bool
    pricing_json: dict[str, Any]
    model_options_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIGatewayResult:
    response: AIResponsePayload
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: Decimal | None
    latency_ms: int
    provider_request_id: str | None


class AIGatewayService:
    """Protocol adapter for current and future model catalogues."""

    @staticmethod
    def model_options(connection: AIProviderSnapshot, model: str) -> dict[str, Any]:
        reasoning = connection.provider == "openai" and bool(
            re.match(r"^(?:o[134](?:-|$)|gpt-5(?:[.-]|$))", model)
        )
        options = {
            "token_parameter": "max_completion_tokens" if reasoning else "max_tokens",
            "supports_temperature": not reasoning,
            "supports_json_mode": connection.supports_json_mode,
        }
        overrides = connection.model_options_json.get(model, {})
        if isinstance(overrides, dict):
            options.update({key: value for key, value in overrides.items() if value is not None})
        return options

    async def execute(
        self,
        *,
        connection: AIProviderSnapshot,
        model: str,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> AIGatewayResult:
        normalized_model = model.strip()
        if not normalized_model:
            raise AIGatewayError(
                "Model is not configured",
                code="model_not_configured",
            )

        started_at = time.monotonic()
        try:
            if connection.api_style == "gemini":
                payload, request_id = await self._call_gemini(
                    connection=connection,
                    model=normalized_model,
                    system_prompt=system_prompt,
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                raw_usage = payload.get("usageMetadata") or {}
                if not isinstance(raw_usage, dict):
                    raw_usage = {}
                output_count = self._optional_int(raw_usage.get("candidatesTokenCount"))
                thought_count = self._optional_int(raw_usage.get("thoughtsTokenCount"))
                usage = {"prompt_tokens": raw_usage.get("promptTokenCount"),
                         "completion_tokens": ((output_count or 0) + (thought_count or 0)
                                               if output_count is not None else None),
                         "total_tokens": raw_usage.get("totalTokenCount")}
            else:
                payload, request_id = await self._call_openai_compatible(
                    connection=connection,
                    model=normalized_model,
                    system_prompt=system_prompt,
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                usage = payload.get("usage") or {}
                if not isinstance(usage, dict):
                    usage = {}
        except AIGatewayError as exc:
            if exc.latency_ms is None:
                exc.latency_ms = int((time.monotonic() - started_at) * 1000)
            raise

        latency_ms = int((time.monotonic() - started_at) * 1000)
        prompt_tokens = self._optional_int(
            usage.get("prompt_tokens") or usage.get("input_tokens")
        )
        completion_tokens = self._optional_int(
            usage.get("completion_tokens") or usage.get("output_tokens")
        )
        total_tokens = self._optional_int(usage.get("total_tokens"))
        if total_tokens is None and (
            prompt_tokens is not None or completion_tokens is not None
        ):
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        estimated_cost_usd = self.estimate_cost(
            pricing_json=connection.pricing_json,
            model=normalized_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        try:
            content, _ = (self._gemini_content_and_usage(payload) if connection.api_style == "gemini"
                          else self._openai_content_and_usage(payload))
            response = self._parse_response(content)
        except AIGatewayError as exc:
            exc.latency_ms = latency_ms
            exc.prompt_tokens = prompt_tokens
            exc.completion_tokens = completion_tokens
            exc.total_tokens = total_tokens
            exc.estimated_cost_usd = estimated_cost_usd
            exc.provider_request_id = request_id
            raise
        return AIGatewayResult(
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            provider_request_id=request_id,
        )

    async def list_models(
        self,
        connection: AIProviderSnapshot,
    ) -> list[str]:
        try:
            response = await provider_request(
                "GET", f"{connection.base_url.rstrip('/')}/models",
                timeout=float(connection.request_timeout_seconds),
                headers=({"x-goog-api-key": connection.api_key} if connection.api_style == "gemini"
                         else self._bearer_headers(connection.api_key)),
            )
            self._raise_for_provider_status(response)
            payload = response.json()
        except AIGatewayError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AIGatewayError(
                "Provider model catalogue is temporarily unavailable",
                code="provider_network_error",
                retriable=True,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AIGatewayError(
                "Provider returned an invalid model catalogue",
                code="invalid_model_catalogue",
            ) from exc

        values = payload.get("models") if connection.api_style == "gemini" else payload.get("data")
        if not isinstance(values, list):
            raise AIGatewayError(
                "Provider response does not contain a model list",
                code="invalid_model_catalogue",
            )
        models: list[str] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            raw_model = item.get("name") if connection.api_style == "gemini" else item.get("id")
            model = str(raw_model or "").strip()
            if connection.api_style == "gemini" and model.startswith("models/"):
                model = model.removeprefix("models/")
            if model and model not in models:
                models.append(model)
        return sorted(models)

    async def _call_openai_compatible(
        self,
        *,
        connection: AIProviderSnapshot,
        model: str,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> tuple[dict[str, Any], str | None]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *[
                    {
                        "role": self._openai_role(item.get("role")),
                        "content": str(item.get("content") or ""),
                    }
                    for item in messages
                ],
            ],
        }
        options = self.model_options(connection, model)
        payload[options["token_parameter"]] = max_output_tokens
        if options["supports_temperature"]:
            payload["temperature"] = temperature
        if options["supports_json_mode"]:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = await provider_request(
                "POST", f"{connection.base_url.rstrip('/')}/chat/completions",
                timeout=float(connection.request_timeout_seconds),
                headers=self._bearer_headers(connection.api_key), json=payload,
            )
            self._raise_for_provider_status(response)
            return response.json(), response.headers.get("x-request-id")
        except AIGatewayError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AIGatewayError(
                "Provider request timed out or could not connect",
                code="provider_network_error",
                retriable=True,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AIGatewayError(
                "Provider returned an unreadable response",
                code="invalid_provider_response",
            ) from exc

    async def _call_gemini(
        self,
        *,
        connection: AIProviderSnapshot,
        model: str,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> tuple[dict[str, Any], str | None]:
        normalized_model = model.removeprefix("models/")
        contents = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": str(item.get("content") or "")}],
            }
            for item in messages
            if str(item.get("content") or "").strip()
        ]
        generation_config: dict[str, Any] = {
            "maxOutputTokens": max_output_tokens,
        }
        options = self.model_options(connection, model)
        if options["supports_temperature"]:
            generation_config["temperature"] = temperature
        if options["supports_json_mode"]:
            generation_config["responseMimeType"] = "application/json"
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents or [{"role": "user", "parts": [{"text": "Ответь согласно инструкции."}]}],
            "generationConfig": generation_config,
        }
        try:
            response = await provider_request(
                "POST", f"{connection.base_url.rstrip('/')}/models/"
                f"{quote(normalized_model, safe='-._')}:generateContent",
                timeout=float(connection.request_timeout_seconds),
                headers={"x-goog-api-key": connection.api_key}, json=payload,
            )
            self._raise_for_provider_status(response)
            return response.json(), response.headers.get("x-request-id")
        except AIGatewayError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AIGatewayError(
                "Provider request timed out or could not connect",
                code="provider_network_error",
                retriable=True,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AIGatewayError(
                "Provider returned an unreadable response",
                code="invalid_provider_response",
            ) from exc

    @staticmethod
    def _openai_content_and_usage(
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIGatewayError(
                "Provider response contains no choices",
                code="empty_provider_response",
                retriable=True,
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise AIGatewayError(
                "Provider response contains no text",
                code="empty_provider_response",
                retriable=True,
            )
        usage = payload.get("usage")
        return content, usage if isinstance(usage, dict) else {}

    @staticmethod
    def _gemini_content_and_usage(
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise AIGatewayError(
                "Provider response contains no candidates",
                code="empty_provider_response",
                retriable=True,
            )
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        text = "".join(
            str(item.get("text") or "")
            for item in (parts if isinstance(parts, list) else [])
            if isinstance(item, dict)
        )
        if not text.strip():
            raise AIGatewayError(
                "Provider response contains no text",
                code="empty_provider_response",
                retriable=True,
            )
        raw_usage = payload.get("usageMetadata")
        raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
        usage = {
            "prompt_tokens": raw_usage.get("promptTokenCount"),
            "completion_tokens": raw_usage.get("candidatesTokenCount"),
            "total_tokens": raw_usage.get("totalTokenCount"),
        }
        return text, usage

    @staticmethod
    def _parse_response(content: str) -> AIResponsePayload:
        match = JSON_FENCE_RE.match(content)
        normalized = match.group(1) if match else content.strip()
        try:
            payload = json.loads(normalized)
            return AIResponsePayload.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise AIGatewayError(
                "Model did not return the required JSON structure",
                code="invalid_structured_output",
                retriable=True,
            ) from exc

    @staticmethod
    def estimate_cost(
        *,
        pricing_json: dict[str, Any],
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> Decimal | None:
        pricing = pricing_json.get(model)
        if not isinstance(pricing, dict):
            return None
        if prompt_tokens is None and completion_tokens is None:
            return None
        try:
            input_rate = Decimal(str(pricing.get("input_usd_per_million") or 0))
            output_rate = Decimal(str(pricing.get("output_usd_per_million") or 0))
        except Exception:
            return None
        if not all(rate.is_finite() and rate >= 0 for rate in (input_rate, output_rate)):
            return None
        if (input_rate > 0 and prompt_tokens is None) or (output_rate > 0 and completion_tokens is None):
            return None
        million = Decimal("1000000")
        return (
            Decimal(prompt_tokens or 0) * input_rate
            + Decimal(completion_tokens or 0) * output_rate
        ) / million

    @staticmethod
    def _bearer_headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _openai_role(value: Any) -> str:
        role = str(value or "user").strip().lower()
        return role if role in {"user", "assistant"} else "user"

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            parsed = int(value) if value is not None and not isinstance(value, bool) else None
            return parsed if parsed is not None and 0 <= parsed <= 2_147_483_647 else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _raise_for_provider_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        status_code = response.status_code
        code = "provider_http_error"
        if status_code in {401, 403}:
            code = "provider_auth_error"
        elif status_code == 429:
            code = "provider_rate_limited"
        elif status_code == 400:
            code = "provider_request_rejected"
        message = f"Provider returned HTTP {status_code}"
        # Provider error bodies can echo credentials and customer prompts.
        # Persist only protocol diagnostics; request IDs are recorded separately.
        raise AIGatewayError(
            message,
            code=code,
            status_code=status_code,
            retriable=status_code == 429 or status_code >= 500,
        )
