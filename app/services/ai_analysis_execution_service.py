"""Analysis-only calls share credential, budget and usage accounting with AI replies."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.models.funnel import FunnelStep
from app.services.ai_analysis_fallback_service import analyse_offline, country_aliases
from app.services.ai_response_execution_service import AIResponseExecutionOutcome, AIResponseExecutionService


def analysis_config(step: FunnelStep) -> dict[str, Any] | None:
    if step.block_type == "ai_analysis":
        return dict(step.config_json or {})
    settings = (step.config_json or {}).get("ai_analysis")
    if step.step_type == "input" and isinstance(settings, dict) and settings.get("enabled") is True:
        return dict(settings)
    return None


def analysis_value_fits_field(field: str | None, value: Any) -> bool:
    limits = {"name": 255, "first_name": 255, "last_name": 255, "username": 255,
              "country": 100, "phone": 50, "call_time_text": 255, "preferred_call_time": 255}
    if field in limits and len(str(value)) > limits[field]:
        return False
    if field == "phone":
        return 10 <= len(re.sub(r"\D", "", str(value))) <= 15
    if field == "age":
        try:
            number = Decimal(str(value))
            return number.is_finite() and number == number.to_integral_value() and 0 <= number <= 120
        except (InvalidOperation, TypeError, ValueError):
            return False
    if field == "has_card":
        return str(value).strip().casefold() in {"true", "false", "yes", "no", "да", "нет", "1", "0"}
    return True


def offline_outcome(answer: str, config: dict[str, Any], *, error_code: str, error_message: str) -> AIResponseExecutionOutcome:
    result = analyse_offline(answer, config)
    return AIResponseExecutionOutcome(
        success=result.next_route_key != "fallback", messages=[], extracted_data={},
        route_key=result.next_route_key, used_fallback=True, error_code=error_code,
        error_message=error_message[:1000], typing_delay_per_char_ms=0, min_delay_ms=0, max_delay_ms=0,
        normalized_answer=result.normalized_answer, source="dictionary",
    )


class AIAnalysisExecutionService:
    def __init__(self, db):
        self.db = db

    async def execute(self, *, chat_id, step, answer: str, still_current=None) -> AIResponseExecutionOutcome:
        config = analysis_config(step)
        if config is None:
            raise ValueError("Analysis is not configured")
        if len(answer) > 12000:
            return offline_outcome("", config, error_code="analysis_input_too_long", error_message="Answer exceeds analysis context limit")
        config["question"] = str((step.config_json or {}).get("prompt") or (step.config_json or {}).get("question_text") or step.title)
        snapshot = FunnelStep(id=step.id, funnel_version_id=step.funnel_version_id, key=step.key,
                              title=step.title, step_type=step.step_type, block_type=step.block_type, config_json=config)
        outcome = await AIResponseExecutionService(self.db).execute(
            chat_id=chat_id, step=snapshot, analysis_input=answer[:12000], still_current=still_current,
        )
        if outcome.error_code == "stale_execution":
            return outcome
        if not outcome.success:
            return offline_outcome(answer, config, error_code=outcome.error_code or "ai_unavailable",
                                   error_message=outcome.error_message or "AI unavailable")
        route = next((item for item in config.get("outcomes", []) if item.get("id") == outcome.route_key), {})
        if (config.get("fallback_type") == "citizenship" and outcome.route_key != "fallback"
                and (outcome.normalized_answer is not None or (route.get("save_answer") is not False
                    and (route.get("country_codes") or route.get("country_match") == "other")))):
            codes = [value.strip().upper() for value in (outcome.normalized_answer or "").split(",") if value.strip()]
            known = country_aliases()[0]
            listed = {str(code).upper() for item in config.get("outcomes", []) if item.get("country_match") != "other" for code in item.get("country_codes", [])}
            allowed = {str(code).upper() for code in route.get("country_codes", [])}
            valid = bool(codes) and all(code in known for code in codes)
            if route.get("country_match") == "other":
                valid = valid and all(code not in listed for code in codes)
            elif allowed:
                valid = valid and all(code in allowed for code in codes)
            if not valid:
                return offline_outcome(answer, config, error_code="invalid_analysis_country",
                                       error_message="AI citizenship result contradicts configured country routing")
            outcome = replace(outcome, normalized_answer=",".join(sorted(set(codes))))
        if step.step_type == "input" and route.get("save_answer") is False:
            outcome = replace(outcome, normalized_answer=None)
        return outcome
