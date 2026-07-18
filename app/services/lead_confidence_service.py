from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.lead_confidence import (
    merged_confidence_thresholds,
    merged_confidence_weights,
)
from app.models.broadcast import BroadcastRecipient
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState, FunnelFieldMapping, FunnelStep, FunnelStepLog
from app.models.lead import Lead, LeadTag
from app.models.project import Project
from app.models.tag import Tag
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.services.lead_auto_submit_queue import enqueue_lead_auto_submit
from app.services.lead_identity_service import LeadIdentityService


@dataclass(frozen=True, slots=True)
class LeadConfidenceResult:
    score_percent: int
    confidence_level: str
    reasons: list[dict[str, Any]]
    meta: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConfidenceCheckResult:
    code: str
    penalty: int
    message: str
    meta: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConfidenceContext:
    lead: Lead
    chat: Chat
    project: Project
    applicable_fields: frozenset[str]
    minimum_amount: float | None
    reask_count: int
    max_answer_pause_hours: float | None
    broadcast_followup: bool


class LeadConfidenceService:
    SCORE_VERSION = 2
    MIN_PHONE_DIGITS = 10
    MAX_PHONE_DIGITS = 15
    LONG_RESPONSE_PAUSE_HOURS = 24

    _SUSPICIOUS_NAME_VALUES = {
        "test",
        "тест",
        "tester",
        "тестер",
        "admin",
        "админ",
        "user",
        "юзер",
        "unknown",
        "неизвестно",
        "нет",
        "none",
        "qwerty",
        "asdf",
    }
    _KNOWN_FIRST_NAMES = {
        "александр", "алексей", "алена", "алина", "анастасия", "андрей", "анна",
        "антон", "артем", "валерия", "виктор", "виктория", "владимир", "дарья",
        "денис", "дмитрий", "евгений", "екатерина", "елена", "иван", "игорь",
        "илья", "ирина", "кирилл", "ксения", "максим", "марина", "мария", "михаил",
        "наталья", "никита", "николай", "олег", "ольга", "павел", "полина", "роман",
        "светлана", "сергей", "софия", "станислав", "татьяна", "тимур", "юлия",
        "abigail", "alejandro", "ana", "andres", "antonio", "camila", "carlos",
        "carmen", "daniel", "david", "diego", "fernando", "francisco", "gabriel",
        "isabella", "javier", "jorge", "jose", "juan", "juliana", "laura", "lucas",
        "luisa", "manuel", "maria", "martin", "mateo", "miguel", "natalia", "pablo",
        "paula", "pedro", "ricardo", "roberto", "sofia", "valentina",
    }
    _COUNTRY_ALIASES = {
        "ru": "RU", "russia": "RU", "россия": "RU", "рф": "RU",
        "kz": "KZ", "kazakhstan": "KZ", "казахстан": "KZ", "казакстан": "KZ",
        "ua": "UA", "ukraine": "UA", "украина": "UA", "україна": "UA",
        "uz": "UZ", "uzbekistan": "UZ", "узбекистан": "UZ",
        "by": "BY", "belarus": "BY", "беларусь": "BY", "белоруссия": "BY",
        "ar": "AR", "argentina": "AR", "аргентина": "AR",
        "mx": "MX", "mexico": "MX", "мексика": "MX", "méxico": "MX",
        "co": "CO", "colombia": "CO", "колумбия": "CO",
        "cl": "CL", "chile": "CL", "чили": "CL",
        "pe": "PE", "peru": "PE", "перу": "PE", "perú": "PE",
        "br": "BR", "brazil": "BR", "brasil": "BR", "бразилия": "BR",
    }
    _CITY_COUNTRIES = {
        "москва": "RU", "moscow": "RU", "санкт петербург": "RU", "питер": "RU",
        "новосибирск": "RU", "екатеринбург": "RU", "казань": "RU", "иркутск": "RU",
        "алматы": "KZ", "алма ата": "KZ", "астана": "KZ", "шымкент": "KZ",
        "караганда": "KZ", "актобе": "KZ", "киев": "UA", "київ": "UA",
        "харьков": "UA", "одесса": "UA", "ташкент": "UZ", "самарканд": "UZ",
        "минск": "BY", "буэнос айрес": "AR", "cordoba": "AR", "кордова": "AR",
        "rosario": "AR", "росарио": "AR", "ciudad de mexico": "MX", "cdmx": "MX",
        "guadalajara": "MX", "monterrey": "MX", "bogota": "CO", "богота": "CO",
        "medellin": "CO", "медельин": "CO", "santiago": "CL", "сантьяго": "CL",
        "lima": "PE", "лима": "PE", "sao paulo": "BR", "rio de janeiro": "BR",
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.identity = LeadIdentityService(db)
        self.partner_repo = PartnerIntegrationRepository(db)

    async def calculate_confidence(self, lead: Lead) -> LeadConfidenceResult:
        context = await self._load_context(lead.id)
        if context is None:
            return LeadConfidenceResult(
                score_percent=0,
                confidence_level="low",
                reasons=[
                    {
                        "code": "lead_unavailable",
                        "penalty": 100,
                        "message": "Лид недоступен для расчета.",
                    }
                ],
                meta={"score_version": self.SCORE_VERSION},
            )

        if not context.project.use_confidence_score:
            current_score = max(0, min(int(context.lead.score_percent or 100), 100))
            thresholds = merged_confidence_thresholds(context.project.confidence_thresholds)
            return LeadConfidenceResult(
                score_percent=current_score,
                confidence_level=self._level_for_score(current_score, thresholds),
                reasons=[],
                meta={
                    "score_version": self.SCORE_VERSION,
                    "calculation_disabled": True,
                },
            )

        vip_tag = await self._vip_tag_match(context)
        if vip_tag is not None:
            thresholds = merged_confidence_thresholds(context.project.confidence_thresholds)
            return LeadConfidenceResult(
                score_percent=100,
                confidence_level=self._level_for_score(100, thresholds),
                reasons=[],
                meta={
                    "score_version": self.SCORE_VERSION,
                    "base_score": 100,
                    "penalty_total": 0,
                    "vip_override": True,
                    "vip_tag": vip_tag,
                    "country_code": self._preferred_country_code(context.lead),
                },
            )

        weights = merged_confidence_weights(context.project.confidence_weights)
        checks: list[ConfidenceCheckResult] = [
            self._check_first_name(context, weights),
            self._check_last_name(context, weights),
            self._check_phone(context, weights),
            self._check_geo(context, weights),
            self._check_card(context, weights),
            self._check_amount(context, weights),
            self._check_tracking_link(context, weights),
            self._check_reask(context, weights),
            self._check_response_pause(context, weights),
            self._check_broadcast_followup(context, weights),
            await self._check_duplicate(context, weights),
        ]
        penalty_total = sum(check.penalty for check in checks)
        score = max(0, min(100 - penalty_total, 100))
        thresholds = merged_confidence_thresholds(context.project.confidence_thresholds)
        reasons = [
            {
                "code": check.code,
                "penalty": check.penalty,
                "message": check.message,
                "meta": check.meta,
            }
            for check in checks
            if check.penalty > 0
        ]
        check_meta = {check.code: check.meta for check in checks}
        geo_meta = check_meta.get("geo", {})
        return LeadConfidenceResult(
            score_percent=score,
            confidence_level=self._level_for_score(score, thresholds),
            reasons=reasons,
            meta={
                "score_version": self.SCORE_VERSION,
                "base_score": 100,
                "penalty_total": penalty_total,
                "weights": weights,
                "thresholds": thresholds,
                "applicable_fields": sorted(context.applicable_fields),
                "country_code": geo_meta.get("country_code"),
                "geo_conflict": bool(geo_meta.get("geo_conflict")),
                "checks": check_meta,
            },
        )

    async def calculate_confidence_by_id(
        self,
        lead_id: UUID,
    ) -> LeadConfidenceResult | None:
        context = await self._load_context(lead_id)
        if context is None:
            return None
        return await self.calculate_confidence(context.lead)

    async def update_lead_score(self, lead_id: UUID) -> int | None:
        context = await self._load_context(lead_id)
        if context is None:
            return None
        lead = context.lead
        if not context.project.use_confidence_score:
            return lead.score_percent

        result = await self.calculate_confidence(lead)
        lead.score_percent = result.score_percent
        lead.confidence_level = result.confidence_level
        lead.confidence_reasons = result.reasons
        lead.confidence_meta = result.meta
        lead.score_calculated_at = datetime.now(timezone.utc)
        lead.score_version = self.SCORE_VERSION
        await self.db.flush()
        await self._route_auto_submit(lead, result)
        return result.score_percent

    async def _route_auto_submit(
        self,
        lead: Lead,
        result: LeadConfidenceResult,
    ) -> None:
        is_vip_override = bool(result.meta.get("vip_override"))
        if not is_vip_override and not await self._questionnaire_is_completed(lead.chat_id):
            return

        integrations = await self.partner_repo.list_auto_submit_by_project(lead.project_id)
        for integration in integrations:
            eligible, reasons = await self.auto_submit_eligibility(
                lead=lead,
                result=result,
                rules=integration.auto_submit_rules or {},
                required_fields=integration.required_fields or [],
            )
            if eligible:
                await self.partner_repo.clear_manual_required_decision(
                    lead_id=lead.id,
                    partner_integration_id=integration.id,
                )
                await enqueue_lead_auto_submit(
                    lead.id,
                    integration.id,
                    forced_manual=is_vip_override,
                )
                continue
            await self.partner_repo.upsert_manual_required_decision(
                lead_id=lead.id,
                partner_integration_id=integration.id,
                reason="; ".join(reasons),
            )
            await self.db.execute(
                Chat.__table__.update()
                .where(Chat.id == lead.chat_id)
                .values(is_read=False, updated_at=func.now())
            )

    async def auto_submit_eligibility(
        self,
        *,
        lead: Lead,
        result: LeadConfidenceResult,
        rules: dict[str, Any],
        required_fields: list[str],
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        try:
            min_score = max(0, min(int(rules.get("min_score", 100)), 100))
        except (TypeError, ValueError):
            min_score = 100
        if result.score_percent < min_score:
            reasons.append(f"score {result.score_percent} ниже порога {min_score}")
        if result.confidence_level == "low":
            reasons.append("низкий уровень уверенности")

        allowed_geos = {
            str(value).strip().upper()
            for value in rules.get("allowed_geos", [])
            if str(value).strip()
        }
        country_code = str(result.meta.get("country_code") or "").upper()
        if allowed_geos and country_code not in allowed_geos:
            reasons.append("гео не входит в разрешенный список")

        checks = result.meta.get("checks") or {}
        if rules.get("require_phone_valid") is True:
            if not bool((checks.get("invalid_phone") or {}).get("valid")):
                reasons.append("телефон не прошел валидацию")
        if rules.get("reject_high_duplicate_risk") is True:
            duplicate_count = int((checks.get("probable_duplicate") or {}).get("count") or 0)
            if duplicate_count > 0:
                reasons.append("высокий риск дубля")
        if rules.get("require_card") is True and lead.has_card is not True:
            reasons.append("не подтверждено наличие карты")
        if rules.get("require_partner_fields") is True:
            missing_fields = self._missing_required_fields(lead, required_fields)
            if missing_fields:
                reasons.append(f"нет обязательных полей: {', '.join(missing_fields)}")
        return not reasons, reasons

    async def _questionnaire_is_completed(self, chat_id: UUID) -> bool:
        completed_at = await self.db.scalar(
            select(ChatFunnelState.completed_at).where(
                ChatFunnelState.chat_id == chat_id,
            )
        )
        return completed_at is not None

    @staticmethod
    def _missing_required_fields(lead: Lead, required_fields: list[str]) -> list[str]:
        custom_fields = lead.custom_fields or {}
        missing: list[str] = []
        for raw_field in required_fields:
            field = str(raw_field).strip()
            if not field:
                continue
            value = getattr(lead, field, None) if hasattr(lead, field) else custom_fields.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field)
        return missing

    def _check_first_name(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        custom = context.lead.custom_fields or {}
        raw_value = custom.get("first_name") or self._first_name(context.lead.name)
        normalized = self._normalize_text(raw_value)
        suspicious = bool(raw_value) and self._is_suspicious_name(normalized)
        penalty = weights["suspicious_first_name"] if suspicious else 0
        return ConfidenceCheckResult(
            code="suspicious_first_name",
            penalty=penalty,
            message="Имя выглядит тестовым или некорректным.",
            meta={
                "present": bool(normalized),
                "known_name": normalized in self._KNOWN_FIRST_NAMES,
                "suspicious": suspicious,
            },
        )

    def _check_last_name(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        custom = context.lead.custom_fields or {}
        raw_value = custom.get("last_name")
        applicable = bool(raw_value) or "last_name" in context.applicable_fields
        normalized = self._normalize_text(raw_value)
        suspicious = applicable and (not normalized or self._is_garbage_text(normalized))
        return ConfidenceCheckResult(
            code="suspicious_last_name",
            penalty=weights["suspicious_last_name"] if suspicious else 0,
            message="Фамилия отсутствует или выглядит некорректно.",
            meta={"applicable": applicable, "present": bool(normalized), "suspicious": suspicious},
        )

    def _check_phone(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        digits = self.identity.normalize_phone(context.lead.phone) or ""
        applicable = bool(context.lead.phone) or "phone" in context.applicable_fields
        valid = self.MIN_PHONE_DIGITS <= len(digits) <= self.MAX_PHONE_DIGITS
        return ConfidenceCheckResult(
            code="invalid_phone",
            penalty=weights["invalid_phone"] if applicable and not valid else 0,
            message="Телефон отсутствует или не нормализуется.",
            meta={"applicable": applicable, "valid": valid, "digits_count": len(digits)},
        )

    def _check_geo(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        sources = self._geo_sources(context.lead)
        codes = [code for _, code in sources if code]
        unique_codes = sorted(set(codes))
        applicable = bool(sources) or bool(
            {"country", "country_code", "geo", "city"} & set(context.applicable_fields)
        )
        conflict = len(unique_codes) > 1
        country_code = codes[0] if codes else None
        if conflict:
            penalty = weights["geo_conflict"]
            message = "Источники гео противоречат друг другу."
        elif applicable and country_code is None:
            penalty = weights["geo_missing"]
            message = "Гео не удалось определить."
        else:
            penalty = 0
            message = "Гео определено."
        return ConfidenceCheckResult(
            code="geo",
            penalty=penalty,
            message=message,
            meta={
                "applicable": applicable,
                "country_code": country_code,
                "geo_conflict": conflict,
                "sources": [{"source": source, "country_code": code} for source, code in sources],
            },
        )

    def _check_card(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        applicable = context.lead.has_card is not None or "has_card" in context.applicable_fields
        if not applicable or context.lead.has_card is True:
            penalty = 0
            code = "card_status"
            message = "Статус карты подтвержден."
        elif context.lead.has_card is False:
            penalty = weights["card_missing"]
            code = "card_status"
            message = "У лида нет карты."
        else:
            penalty = weights["card_unknown"]
            code = "card_status"
            message = "Статус карты не определен."
        return ConfidenceCheckResult(
            code=code,
            penalty=penalty,
            message=message,
            meta={"applicable": applicable, "value": context.lead.has_card},
        )

    def _check_amount(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        custom = context.lead.custom_fields or {}
        raw_value = next(
            (
                custom.get(key)
                for key in ("expected_start_amount", "budget", "amount")
                if custom.get(key) is not None
            ),
            None,
        )
        amount = self._float_value(raw_value)
        applicable = raw_value is not None or bool(
            {"expected_start_amount", "budget", "amount"} & set(context.applicable_fields)
        )
        if applicable and amount is None:
            penalty = weights["amount_unknown"]
            message = "Ожидаемая сумма не определена."
        elif amount is not None and context.minimum_amount is not None and amount < context.minimum_amount:
            penalty = weights["amount_below_minimum"]
            message = "Ожидаемая сумма ниже минимальной."
        else:
            penalty = 0
            message = "Ожидаемая сумма соответствует условиям."
        return ConfidenceCheckResult(
            code="start_amount",
            penalty=penalty,
            message=message,
            meta={
                "applicable": applicable,
                "value": amount,
                "minimum": context.minimum_amount,
            },
        )

    @staticmethod
    def _check_tracking_link(
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        present = context.chat.tracking_link_id is not None
        return ConfidenceCheckResult(
            code="missing_tracking_link",
            penalty=0 if present else weights["missing_tracking_link"],
            message="Нет привязанной трекинг-ссылки.",
            meta={"present": present},
        )

    @staticmethod
    def _check_reask(
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        return ConfidenceCheckResult(
            code="reask",
            penalty=weights["reask"] if context.reask_count > 0 else 0,
            message="Боту пришлось повторно запросить данные.",
            meta={"count": context.reask_count},
        )

    def _check_response_pause(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        long_pause = bool(
            context.max_answer_pause_hours is not None
            and context.max_answer_pause_hours >= self.LONG_RESPONSE_PAUSE_HOURS
        )
        return ConfidenceCheckResult(
            code="long_response_pause",
            penalty=weights["long_response_pause"] if long_pause else 0,
            message="Между ответами лида была длительная пауза.",
            meta={
                "threshold_hours": self.LONG_RESPONSE_PAUSE_HOURS,
                "max_pause_hours": context.max_answer_pause_hours,
            },
        )

    @staticmethod
    def _check_broadcast_followup(
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        return ConfidenceCheckResult(
            code="broadcast_followup",
            penalty=weights["broadcast_followup"] if context.broadcast_followup else 0,
            message="Лида догоняли рассылкой.",
            meta={"present": context.broadcast_followup},
        )

    async def _check_duplicate(
        self,
        context: ConfidenceContext,
        weights: dict[str, int],
    ) -> ConfidenceCheckResult:
        duplicates = await self.identity.find_duplicates(context.lead.id, context.lead.project_id)
        return ConfidenceCheckResult(
            code="probable_duplicate",
            penalty=weights["probable_duplicate"] if duplicates else 0,
            message="Найден вероятный дубль лида.",
            meta={"count": len(duplicates)},
        )

    async def _load_context(self, lead_id: UUID) -> ConfidenceContext | None:
        result = await self.db.execute(
            select(Lead, Chat, Project)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(Project, Project.id == Lead.project_id)
            .where(
                Lead.id == lead_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
                Chat.is_deleted.is_(False),
                Project.is_deleted.is_(False),
            )
        )
        row = result.first()
        if row is None:
            return None
        lead, chat, project = row[0], row[1], row[2]
        applicable_fields, minimum_amount = await self._load_applicable_fields(lead, chat)
        reask_count = await self._load_reask_count(chat.id)
        max_answer_pause_hours = await self._load_max_answer_pause_hours(lead.id)
        broadcast_followup = await self._load_broadcast_followup(lead.id)
        return ConfidenceContext(
            lead=lead,
            chat=chat,
            project=project,
            applicable_fields=frozenset(applicable_fields),
            minimum_amount=minimum_amount,
            reask_count=reask_count,
            max_answer_pause_hours=max_answer_pause_hours,
            broadcast_followup=broadcast_followup,
        )

    async def _vip_tag_match(self, context: ConfidenceContext) -> str | None:
        configured = {
            str(value).strip().casefold()
            for value in (context.project.vip_tags or [])
            if str(value).strip()
        }
        if not configured:
            return None
        result = await self.db.execute(
            select(Tag.id, Tag.name)
            .join(LeadTag, LeadTag.tag_id == Tag.id)
            .where(LeadTag.lead_id == context.lead.id)
        )
        for tag_id, tag_name in result.all():
            if str(tag_id).casefold() in configured or str(tag_name).strip().casefold() in configured:
                return str(tag_name)
        return None

    async def _load_applicable_fields(
        self,
        lead: Lead,
        chat: Chat,
    ) -> tuple[set[str], float | None]:
        state_result = await self.db.execute(
            select(ChatFunnelState.funnel_version_id, ChatFunnelState.runtime_json)
            .where(ChatFunnelState.chat_id == chat.id)
            .limit(1)
        )
        state_row = state_result.first()
        version_id = state_row[0] if state_row is not None else None
        if version_id is None:
            version_id = await self.db.scalar(
                select(FunnelStepLog.funnel_version_id)
                .where(FunnelStepLog.lead_id == lead.id)
                .order_by(FunnelStepLog.created_at.desc())
                .limit(1)
            )
        if version_id is None:
            return set(), None

        fields = set(
            (
                await self.db.execute(
                    select(FunnelFieldMapping.lead_field_key).where(
                        FunnelFieldMapping.funnel_version_id == version_id
                    )
                )
            ).scalars().all()
        )
        step_rows = (
            await self.db.execute(
                select(FunnelStep.block_type, FunnelStep.config_json).where(
                    FunnelStep.funnel_version_id == version_id
                )
            )
        ).all()
        minimum_amount: float | None = None
        fallback_fields = {
            "ask_phone": "phone",
            "ask_name": "first_name",
            "ask_last_name": "last_name",
            "ask_country": "country",
            "ask_city": "city",
            "ask_card": "has_card",
            "ask_has_card": "has_card",
            "ask_budget": "budget",
            "ask_expected_start_amount": "expected_start_amount",
        }
        for block_type, raw_config in step_rows:
            config = raw_config if isinstance(raw_config, dict) else {}
            field = next(
                (
                    str(config.get(key)).strip()
                    for key in (
                        "save_to",
                        "field_key",
                        "custom_field_key",
                        "lead_field_key",
                        "variable_name",
                    )
                    if config.get(key)
                ),
                None,
            )
            field = field or fallback_fields.get(block_type)
            if field:
                fields.add(field)
            if field in {"expected_start_amount", "budget", "amount"}:
                validation = config.get("validation") if isinstance(config.get("validation"), dict) else {}
                candidate = next(
                    (
                        self._float_value(value)
                        for value in (
                            validation.get("min"),
                            validation.get("min_value"),
                            config.get("min"),
                            config.get("min_value"),
                            config.get("minimum"),
                        )
                        if value is not None
                    ),
                    None,
                )
                if candidate is not None:
                    minimum_amount = max(minimum_amount or candidate, candidate)
        return fields, minimum_amount

    async def _load_reask_count(self, chat_id: UUID) -> int:
        runtime_json = await self.db.scalar(
            select(ChatFunnelState.runtime_json).where(ChatFunnelState.chat_id == chat_id)
        )
        try:
            return max(int((runtime_json or {}).get("confidence_reask_count") or 0), 0)
        except (TypeError, ValueError):
            return 0

    async def _load_max_answer_pause_hours(self, lead_id: UUID) -> float | None:
        rows = list(
            (
                await self.db.execute(
                    select(FunnelStepLog.created_at)
                    .where(
                        FunnelStepLog.lead_id == lead_id,
                        FunnelStepLog.event_type == "answered",
                    )
                    .order_by(FunnelStepLog.created_at.asc())
                )
            ).scalars().all()
        )
        if len(rows) < 2:
            return None
        return max((right - left).total_seconds() / 3600 for left, right in zip(rows, rows[1:]))

    async def _load_broadcast_followup(self, lead_id: UUID) -> bool:
        count = await self.db.scalar(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.lead_id == lead_id,
                BroadcastRecipient.sent_at.is_not(None),
            )
        )
        return bool(count)

    def _geo_sources(self, lead: Lead) -> list[tuple[str, str | None]]:
        custom = lead.custom_fields or {}
        raw_sources: list[tuple[str, Any]] = [
            ("lead.country", lead.country),
            ("custom.country_code", custom.get("country_code")),
            ("custom.country", custom.get("country")),
            ("custom.geo", custom.get("geo")),
            ("custom.city", custom.get("city")),
        ]
        for container_name in ("utm", "utm_data", "fb_data"):
            container = custom.get(container_name)
            if isinstance(container, dict):
                raw_sources.extend(
                    [
                        (f"{container_name}.country_code", container.get("country_code")),
                        (f"{container_name}.country", container.get("country")),
                        (f"{container_name}.geo", container.get("geo")),
                        (f"{container_name}.city", container.get("city")),
                    ]
                )
        normalized: list[tuple[str, str | None]] = []
        for source, value in raw_sources:
            if value is None or not str(value).strip():
                continue
            normalized.append((source, self._country_code(value)))
        return normalized

    def _preferred_country_code(self, lead: Lead) -> str | None:
        return next((code for _, code in self._geo_sources(lead) if code), None)

    @classmethod
    def _country_code(cls, value: Any) -> str | None:
        normalized = cls._normalize_text(value)
        return cls._COUNTRY_ALIASES.get(normalized) or cls._CITY_COUNTRIES.get(normalized)

    @classmethod
    def _is_suspicious_name(cls, normalized: str) -> bool:
        if not normalized:
            return False
        if normalized in cls._KNOWN_FIRST_NAMES:
            return False
        return normalized in cls._SUSPICIOUS_NAME_VALUES or cls._is_garbage_text(normalized)

    @classmethod
    def _is_garbage_text(cls, normalized: str) -> bool:
        compact = normalized.replace(" ", "")
        if not compact or any(character.isdigit() for character in compact):
            return True
        if len(compact) < 2 or not any(character.isalpha() for character in compact):
            return True
        return bool(re.search(r"(.)\1{3,}", compact))

    @staticmethod
    def _first_name(value: str | None) -> str | None:
        if not value:
            return None
        parts = value.strip().split()
        return parts[0] if parts else None

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        normalized = unicodedata.normalize("NFKD", str(value).strip().lower())
        normalized = "".join(character for character in normalized if not unicodedata.combining(character))
        return re.sub(r"[^a-zа-яёіїєґ\s-]", "", normalized).replace("-", " ").strip()

    @staticmethod
    def _float_value(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"-?\d+(?:[\s.,]\d+)*", str(value))
        if match is None:
            return None
        normalized = match.group(0).replace(" ", "").replace(",", ".")
        try:
            return float(normalized)
        except ValueError:
            return None

    @staticmethod
    def _level_for_score(score_percent: int, thresholds: dict[str, int]) -> str:
        if score_percent >= thresholds["high_min"]:
            return "high"
        if score_percent >= thresholds["medium_min"]:
            return "medium"
        return "low"
