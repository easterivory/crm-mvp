from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ChatEventType, LeadStatusCode
from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration
from app.repositories.lead_repository import LeadRepository
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.services.chat_audit_service import ChatAuditService

logger = logging.getLogger(__name__)


class PostbackService:
    COMPLETED_STATUS = "completed"
    FAILED_STATUS = "failed"
    DUPLICATE_STATUS = "duplicate"

    DEFAULT_STATUS_TO_LEAD_STATUS = {
        "completed": [LeadStatusCode.SUBMITTED],
        "success": [LeadStatusCode.SUBMITTED],
        "accepted": [LeadStatusCode.SUBMITTED],
        "ok": [LeadStatusCode.SUBMITTED],
        "duplicate": ["duplicate", LeadStatusCode.LOST],
        "deposit": ["deposit", LeadStatusCode.QUALIFIED],
        "trash": ["trash", LeadStatusCode.LOST],
        "rejected": ["rejected", LeadStatusCode.LOST],
        "reject": ["rejected", LeadStatusCode.LOST],
        "failed": ["rejected", LeadStatusCode.LOST],
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PartnerIntegrationRepository(db)
        self.lead_repo = LeadRepository(db)
        self.audit_service = ChatAuditService(db)

    def build_payload(self, lead: Lead, integration: PartnerIntegration) -> dict[str, Any]:
        mapping = integration.field_mapping or {}
        payload: dict[str, Any] = {}

        if mapping:
            for partner_field, crm_path in mapping.items():
                value = self._get_path_value(lead, crm_path)
                self._set_path_value(payload, partner_field, self._json_safe(value))
        else:
            payload = self._default_lead_payload(lead)

        for required_field in integration.required_fields or []:
            value = self._get_path_value(payload, required_field)
            if self._is_empty(value):
                raise ValueError(
                    f"Пропуск отправки: отсутствует обязательное поле '{required_field}'"
                )

        return payload

    def parse_response(
        self,
        response_json: dict[str, Any],
        integration: PartnerIntegration,
    ) -> dict[str, Any]:
        mapping = integration.response_mapping or {}

        status_path = mapping.get("status_path") or mapping.get("success_key") or "status"
        raw_status = self._get_path_value(response_json, status_path)
        normalized_status = self._normalize_status(raw_status)

        duplicate_key = mapping.get("duplicate_key")
        duplicate_value = mapping.get("duplicate_value")
        if duplicate_key and duplicate_value:
            duplicate_candidate = self._get_path_value(response_json, duplicate_key)
            if self._normalize_status(duplicate_candidate) == self._normalize_status(
                duplicate_value
            ):
                return self._parsed_response(
                    status=self.DUPLICATE_STATUS,
                    response_json=response_json,
                    integration=integration,
                    raw_status=duplicate_candidate,
                    error_message=self._response_error(response_json, integration),
                )

        success_values = self._response_values(mapping, "success_values", "success_value")
        duplicate_values = self._response_values(mapping, "duplicate_values", "duplicate_value")
        rejected_values = self._response_values(mapping, "rejected_values", "rejected_value")

        if normalized_status in duplicate_values:
            parsed_status = self.DUPLICATE_STATUS
        elif normalized_status in success_values:
            parsed_status = self.COMPLETED_STATUS
        elif normalized_status in rejected_values:
            parsed_status = self.FAILED_STATUS
        else:
            parsed_status = self.FAILED_STATUS

        return self._parsed_response(
            status=parsed_status,
            response_json=response_json,
            integration=integration,
            raw_status=raw_status,
            error_message=(
                self._response_error(response_json, integration)
                if parsed_status == self.FAILED_STATUS
                else None
            ),
        )

    async def process_pending_submissions(self, limit: int = 20) -> int:
        submissions = await self.repo.list_pending_submissions(limit=limit)
        processed = 0
        for submission in submissions:
            await self.process_submission(submission.id)
            processed += 1
        return processed

    async def process_submission(self, submission_id: UUID) -> dict[str, Any]:
        submission = await self.repo.get_submission(submission_id)
        if submission is None:
            return {"status": self.FAILED_STATUS, "error": "Submission not found"}
        await self._send_submission(submission)
        return {"status": submission.status, "submission_id": str(submission.id)}

    async def process_partner_postback(
        self,
        integration_id: UUID,
        payload: dict[str, Any],
        query_params: dict[str, Any],
    ) -> dict[str, Any]:
        integration = await self.repo.get_by_id(integration_id)
        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner integration not found",
            )

        submission_id = self._as_uuid(
            self._first_value(
                payload,
                query_params,
                [
                    (integration.response_mapping or {}).get("submission_id_path"),
                    "lead_submission_id",
                    "submission_id",
                    "crm_submission_id",
                ],
            )
        )
        lead_id = self._as_uuid(
            self._first_value(
                payload,
                query_params,
                [
                    (integration.response_mapping or {}).get("lead_id_path"),
                    "lead_id",
                    "crm_lead_id",
                    "internal_lead_id",
                ],
            )
        )
        external_id_value = self._first_value(
            payload,
            query_params,
            [
                (integration.response_mapping or {}).get("external_id_path"),
                "partner_lead_id",
                "external_id",
                "click_id",
                "tracker_link_id",
            ],
        )
        external_id = str(external_id_value).strip() if external_id_value is not None else None

        submission = await self.repo.find_submission_for_partner_postback(
            partner_integration_id=integration.id,
            submission_id=submission_id,
            lead_id=lead_id,
            external_id=external_id or None,
        )
        if submission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead submission not found for partner postback",
            )

        partner_status = self._partner_status_from_postback(payload, query_params, integration)
        old_status = submission.partner_status
        submission.partner_status = partner_status
        submission.partner_status_updated_at = datetime.now(timezone.utc)

        lead = submission.lead
        if lead is not None:
            await self._apply_partner_status_to_lead(
                lead=lead,
                integration=integration,
                partner_status=partner_status,
            )
            await self._log_partner_status_event(
                lead=lead,
                old_status=old_status,
                partner_status=partner_status,
                payload=payload,
            )

        await self.db.flush()
        logger.info(
            "Partner postback processed integration_id=%s submission_id=%s partner_status=%s",
            integration.id,
            submission.id,
            partner_status,
        )
        return {
            "status": "processed",
            "submission_id": str(submission.id),
            "lead_id": str(submission.lead_id),
            "partner_status": partner_status,
        }

    async def test_connection(self, integration: PartnerIntegration) -> dict[str, Any]:
        try:
            payload = self.build_payload(self._test_lead(integration), integration)
        except ValueError as exc:
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": False,
                "accepted": False,
                "status": "mapping_failed",
                "request_payload": {},
                "response_payload": None,
                "parsed_response": None,
                "error_message": str(exc),
            }

        request = self._build_request(integration)
        timeout_seconds = float((integration.retry_config or {}).get("timeout_seconds") or 30)
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    integration.postback_url,
                    json=payload,
                    headers=request["headers"],
                    params=request["params"],
                )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": True,
                "accepted": False,
                "status": "timeout",
                "request_payload": payload,
                "response_payload": None,
                "parsed_response": None,
                "error_message": "Request timeout",
            }
        except Exception as exc:
            logger.exception("Partner test connection failed integration_id=%s", integration.id)
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": True,
                "accepted": False,
                "status": "request_failed",
                "request_payload": payload,
                "response_payload": None,
                "parsed_response": None,
                "error_message": str(exc)[:1000],
            }

        response_json = self._response_json(response)
        parsed = self.parse_response(response_json, integration)
        connected = response.status_code < 500
        accepted = response.status_code < 400 and parsed["status"] == self.COMPLETED_STATUS
        return {
            "ok": connected and accepted,
            "connected": connected,
            "mapping_valid": True,
            "accepted": accepted,
            "status": parsed["status"],
            "status_code": response.status_code,
            "request_payload": payload,
            "response_payload": {
                "json": response_json,
                "body": response.text[:1000],
            },
            "parsed_response": parsed,
            "error_message": parsed.get("error_message")
            or (f"HTTP {response.status_code}" if response.status_code >= 400 else None),
        }

    async def _send_submission(self, submission: LeadSubmission) -> None:
        if submission.status != "pending":
            return
        submission.status = "sending"
        await self.db.flush()

        lead = submission.lead
        integration = submission.partner_integration
        if lead is None or integration is None:
            self._mark_failed(submission, "Lead or partner integration not found")
            await self.db.flush()
            return
        if lead.project_id != integration.project_id:
            self._mark_failed(submission, "Lead and partner integration project mismatch")
            await self.db.flush()
            return
        if not integration.is_active:
            self._mark_failed(submission, "Partner integration is not active")
            await self.db.flush()
            return

        try:
            payload = self.build_payload(lead, integration)
        except ValueError as exc:
            self._mark_failed(submission, str(exc))
            await self.db.flush()
            logger.warning(
                "Postback skipped lead_id=%s integration_id=%s reason=%s",
                lead.id,
                integration.id,
                exc,
            )
            return

        submission.request_payload = payload
        request = self._build_request(integration)
        retry_config = integration.retry_config or {}
        max_attempts = int(retry_config.get("max_attempts") or 1)
        delays = [int(delay) for delay in retry_config.get("delays_seconds") or []]
        timeout_seconds = float(retry_config.get("timeout_seconds") or 30)

        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.post(
                        integration.postback_url,
                        json=payload,
                        headers=request["headers"],
                        params=request["params"],
                    )
                await self._apply_http_response(submission, response, integration, lead)
                await self.db.flush()
                return
            except httpx.TimeoutException:
                last_error = "Request timeout"
                logger.warning(
                    "Postback timeout lead_id=%s integration_id=%s attempt=%s/%s",
                    lead.id,
                    integration.id,
                    attempt,
                    max_attempts,
                )
            except Exception as exc:
                last_error = str(exc)[:1000]
                logger.exception(
                    "Postback failed lead_id=%s integration_id=%s attempt=%s/%s",
                    lead.id,
                    integration.id,
                    attempt,
                    max_attempts,
                )

            if attempt < max_attempts and delays:
                delay_index = min(attempt - 1, len(delays) - 1)
                await self._sleep(delays[delay_index])

        self._mark_failed(submission, last_error or "Postback failed")
        await self.db.flush()

    async def _apply_http_response(
        self,
        submission: LeadSubmission,
        response: httpx.Response,
        integration: PartnerIntegration,
        lead: Lead,
    ) -> None:
        response_json = self._response_json(response)
        parsed = self.parse_response(response_json, integration)
        forced_http_failure = False
        if response.status_code >= 400 and parsed["status"] == self.COMPLETED_STATUS:
            forced_http_failure = True
            parsed = {
                **parsed,
                "status": self.FAILED_STATUS,
                "error_message": f"HTTP {response.status_code}: {response.text[:500]}",
            }

        submission.response_payload = {
            "status_code": response.status_code,
            "json": response_json,
            "body": response.text[:1000],
            "parsed": parsed,
        }
        submission.status = parsed["status"]
        submission.error_message = parsed.get("error_message")
        submission.partner_status = parsed.get("partner_status")
        if submission.partner_status:
            submission.partner_status_updated_at = datetime.now(timezone.utc)
        submission.completed_at = datetime.now(timezone.utc)

        if not forced_http_failure and submission.status in {
            self.COMPLETED_STATUS,
            self.DUPLICATE_STATUS,
        }:
            await self._apply_partner_status_to_lead(
                lead=lead,
                integration=integration,
                partner_status=submission.partner_status or submission.status,
            )
        elif (
            not forced_http_failure
            and submission.status == self.FAILED_STATUS
            and submission.partner_status
        ):
            await self._apply_partner_status_to_lead(
                lead=lead,
                integration=integration,
                partner_status=submission.partner_status,
            )
        logger.info(
            "Postback HTTP response parsed lead_id=%s integration_id=%s status=%s",
            lead.id,
            integration.id,
            submission.status,
        )

    async def _apply_partner_status_to_lead(
        self,
        *,
        lead: Lead,
        integration: PartnerIntegration,
        partner_status: str,
    ) -> None:
        for status_code in self._lead_status_candidates(integration, partner_status):
            updated = await self.lead_repo.set_status_by_code(
                lead.id,
                lead.project_id,
                status_code,
            )
            if updated is not None:
                return
        logger.warning(
            "Partner status could not be mapped to an existing lead status "
            "lead_id=%s partner_status=%s",
            lead.id,
            partner_status,
        )

    async def _log_partner_status_event(
        self,
        *,
        lead: Lead,
        old_status: str | None,
        partner_status: str,
        payload: dict[str, Any],
    ) -> None:
        amount = self._first_existing_value(payload, ["amount", "deposit", "sum", "value"])
        suffix = f" ({amount})" if amount not in (None, "") else ""
        await self.audit_service.log_event(
            chat_id=lead.chat_id,
            user_id=None,
            event_type=ChatEventType.STATUS_CHANGE,
            old_value=old_status,
            new_value=f"Партнер обновил статус: {partner_status}{suffix}",
            project_id=lead.project_id,
        )

    def _build_request(self, integration: PartnerIntegration) -> dict[str, dict[str, str]]:
        headers = {"Content-Type": "application/json"}
        params: dict[str, str] = {}
        auth_config = dict(integration.auth_config or {})
        token = auth_config.get("token") or integration.auth_token
        if not token:
            return {"headers": headers, "params": params}

        if integration.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif integration.auth_type == "query_param":
            param_name = auth_config.get("query_param_name")
            if param_name:
                params[str(param_name)] = str(token)
        elif integration.auth_type == "header":
            header_name = auth_config.get("header_name") or "Authorization"
            headers[str(header_name)] = str(token)
        return {"headers": headers, "params": params}

    def _parsed_response(
        self,
        *,
        status: str,
        response_json: dict[str, Any],
        integration: PartnerIntegration,
        raw_status: Any,
        error_message: str | None,
    ) -> dict[str, Any]:
        mapping = integration.response_mapping or {}
        external_id = self._get_optional_path_value(response_json, mapping.get("external_id_path"))
        partner_status = self._get_optional_path_value(
            response_json,
            mapping.get("partner_status_path"),
        )
        partner_status = partner_status if partner_status is not None else raw_status
        return {
            "status": status,
            "error_message": error_message,
            "partner_status": str(partner_status) if partner_status is not None else None,
            "external_id": str(external_id) if external_id is not None else None,
        }

    def _response_error(
        self,
        response_json: dict[str, Any],
        integration: PartnerIntegration,
    ) -> str | None:
        mapping = integration.response_mapping or {}
        error_path = mapping.get("error_path")
        if error_path:
            error_value = self._get_path_value(response_json, error_path)
            if error_value is not None:
                return str(error_value)
        for fallback_path in ("error", "message", "description", "detail"):
            error_value = self._get_path_value(response_json, fallback_path)
            if error_value is not None:
                return str(error_value)
        return None

    def _lead_status_candidates(
        self,
        integration: PartnerIntegration,
        partner_status: str,
    ) -> list[str]:
        normalized = self._normalize_status(partner_status)
        status_mapping = (integration.response_mapping or {}).get("status_mapping") or {}
        configured = status_mapping.get(partner_status) or status_mapping.get(normalized)
        candidates: list[str] = []
        if configured:
            candidates.append(str(configured))
        candidates.extend(self.DEFAULT_STATUS_TO_LEAD_STATUS.get(normalized, []))

        unique_candidates: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique_candidates:
                unique_candidates.append(candidate)
        return unique_candidates

    def _partner_status_from_postback(
        self,
        payload: dict[str, Any],
        query_params: dict[str, Any],
        integration: PartnerIntegration,
    ) -> str:
        mapping = integration.response_mapping or {}
        value = self._first_value(
            payload,
            query_params,
            [
                mapping.get("partner_status_path"),
                mapping.get("status_path"),
                "partner_status",
                "status",
                "event",
                "result",
            ],
        )
        if value is None or str(value).strip() == "":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Partner status is missing in postback payload",
            )
        return str(value).strip()

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {"raw": response.text}
        return data if isinstance(data, dict) else {"data": data}

    @classmethod
    def _response_values(
        cls,
        mapping: dict[str, Any],
        list_key: str,
        scalar_key: str,
    ) -> set[str]:
        values = list(mapping.get(list_key) or [])
        scalar = mapping.get(scalar_key)
        if scalar is not None:
            values.append(scalar)
        return {cls._normalize_status(value) for value in values if value is not None}

    @staticmethod
    def _default_lead_payload(lead: Lead) -> dict[str, Any]:
        return {
            "lead_id": str(lead.id),
            "name": lead.name,
            "phone": lead.phone,
            "username": lead.username,
            "age": lead.age,
            "country": lead.country,
            "call_time": lead.call_time_text,
            "has_card": lead.has_card,
            "score_percent": lead.score_percent,
            "custom_fields": lead.custom_fields,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        }

    @staticmethod
    def _test_lead(integration: PartnerIntegration) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        lead_id = uuid4()
        return SimpleNamespace(
            id=lead_id,
            project_id=integration.project_id,
            chat_id=uuid4(),
            name="CRM Test Lead",
            phone="+10000000000",
            username="crm_test_lead",
            age=30,
            country="US",
            call_time_text="test",
            has_card=True,
            score_percent=100,
            custom_fields={
                "deposit": 100,
                "click_id": f"test-click-{lead_id}",
                "tracker_link_id": f"test-tracker-{lead_id}",
                "source": "crm_test_connection",
                "is_test": True,
            },
            created_at=now,
        )

    @classmethod
    def _get_optional_path_value(cls, source: Any, path: Any) -> Any:
        if not path:
            return None
        return cls._get_path_value(source, str(path))

    @classmethod
    def _get_path_value(cls, source: Any, path: str) -> Any:
        if source is None or not path:
            return None
        current = source
        for part in path.split("."):
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if index < len(current) else None
            else:
                current = getattr(current, part, None)
        return current

    @classmethod
    def _set_path_value(cls, target: dict[str, Any], path: str, value: Any) -> None:
        parts = [part for part in path.split(".") if part]
        if not parts:
            return
        current = target
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = value

    @classmethod
    def _first_value(
        cls,
        payload: dict[str, Any],
        query_params: dict[str, Any],
        paths: list[str | None],
    ) -> Any:
        for path in paths:
            if not path:
                continue
            for source in (payload, query_params):
                value = cls._get_path_value(source, path)
                if isinstance(value, list):
                    value = value[0] if value else None
                if value is not None and str(value).strip() != "":
                    return value
        return None

    @classmethod
    def _first_existing_value(cls, payload: dict[str, Any], paths: list[str]) -> Any:
        for path in paths:
            value = cls._get_path_value(payload, path)
            if value is not None:
                return value
        return None

    @staticmethod
    def _is_empty(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(item) for item in value]
        return value

    @staticmethod
    def _normalize_status(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _as_uuid(value: Any) -> UUID | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    async def _sleep(seconds: int) -> None:
        await asyncio.sleep(seconds)

    @staticmethod
    def _mark_failed(submission: LeadSubmission, error: str) -> None:
        submission.status = PostbackService.FAILED_STATUS
        submission.error_message = error[:1000]
        submission.completed_at = datetime.now(timezone.utc)
