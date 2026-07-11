from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import secrets
import string
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ChatEventType, LeadStatusCode
from app.core.lead_names import compose_lead_name, resolve_lead_names, split_lead_name
from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration
from app.repositories.lead_repository import LeadRepository
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.services.chat_audit_service import ChatAuditService
from app.services.google_sheets_trigger_service import GoogleSheetsTriggerService
from app.services.lead_identity_service import LeadIdentityService

logger = logging.getLogger(__name__)


class PostbackService:
    COMPLETED_STATUS = "completed"
    FAILED_STATUS = "failed"
    DUPLICATE_STATUS = "duplicate"
    TEMPLATE_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.]{0,127})\s*}}")
    FULL_TEMPLATE_PATTERN = re.compile(r"^\s*{{\s*([A-Za-z_][A-Za-z0-9_.]{0,127})\s*}}\s*$")

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
        self.identity_service = LeadIdentityService(db)
        self.google_sheets_trigger = GoogleSheetsTriggerService(db)

    def build_payload(
        self,
        lead: Lead,
        integration: PartnerIntegration,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_config = getattr(integration, "request_config", None) or {}
        payload_template = request_config.get("payload_template") or {}
        mapping = integration.field_mapping or {}
        template_context = context or self._build_template_context(lead, integration)

        if payload_template:
            rendered = self._render_template_value(payload_template, template_context)
            if not isinstance(rendered, dict):
                raise ValueError("Шаблон тела запроса должен быть JSON-объектом")
            payload = (
                self._omit_null_dict_values(rendered)
                if request_config.get("omit_null_values", True)
                else rendered
            )
        elif mapping:
            payload = {}
            for partner_field, crm_path in mapping.items():
                if self.TEMPLATE_PATTERN.search(crm_path):
                    value = self._render_template_value(crm_path, template_context)
                else:
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

    def redact_payload(
        self,
        payload: dict[str, Any],
        integration: PartnerIntegration,
    ) -> dict[str, Any]:
        secrets_to_hide = {
            str(value)
            for value in (getattr(integration, "request_config", None) or {})
            .get("secret_variables", {})
            .values()
            if value not in (None, "")
        }

        def redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {str(key): redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            if not isinstance(value, str):
                return value
            result = value
            for secret_value in secrets_to_hide:
                result = result.replace(secret_value, "***")
            return result

        return redact(payload)

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
            local_status_code = await self._apply_partner_status_to_lead(
                lead=lead,
                integration=integration,
                partner_status=partner_status,
            )
            self._apply_validation_outcome(submission, local_status_code)
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
        test_lead = self._test_lead(integration)
        context = self._build_template_context(test_lead, integration)
        try:
            payload = self.build_payload(
                test_lead,
                integration,
                context=context,
            )
            request = self.build_request(integration, context=context)
        except ValueError as exc:
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": False,
                "accepted": False,
                "status": "mapping_failed",
                "request_payload": {},
                "request_metadata": {},
                "response_payload": None,
                "parsed_response": None,
                "error_message": str(exc),
            }

        timeout_seconds = float((integration.retry_config or {}).get("timeout_seconds") or 30)
        request_metadata = self.request_metadata(integration, request)
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await self.send_http_request(
                    client,
                    integration,
                    payload,
                    request,
                )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": True,
                "accepted": False,
                "status": "timeout",
                "request_payload": self.redact_payload(payload, integration),
                "request_metadata": request_metadata,
                "response_payload": None,
                "parsed_response": None,
                "error_message": "Request timeout",
            }
        except httpx.ConnectError as exc:
            error_message = self._connection_error_message(integration.postback_url, exc)
            logger.warning(
                "Partner connection failed integration_id=%s reason=%s",
                integration.id,
                error_message,
            )
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": True,
                "accepted": False,
                "status": "dns_error" if self._is_dns_error(exc) else "connection_failed",
                "request_payload": self.redact_payload(payload, integration),
                "request_metadata": request_metadata,
                "response_payload": None,
                "parsed_response": None,
                "error_message": error_message,
            }
        except Exception as exc:
            logger.exception("Partner test connection failed integration_id=%s", integration.id)
            return {
                "ok": False,
                "connected": False,
                "mapping_valid": True,
                "accepted": False,
                "status": "request_failed",
                "request_payload": self.redact_payload(payload, integration),
                "request_metadata": request_metadata,
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
            "request_payload": self.redact_payload(payload, integration),
            "request_metadata": request_metadata,
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
        conflict = await self.identity_service.find_partner_submission_conflict(
            lead_id=lead.id,
            project_id=lead.project_id,
            partner_integration=integration,
        )
        if conflict is not None:
            duplicate = conflict.duplicate
            blocking = conflict.blocking_submission
            self._mark_failed(
                submission,
                (
                    "Duplicate conflict: matching lead "
                    f"{duplicate.lead_id} in project '{duplicate.project_name}' "
                    f"was already submitted to advertiser '{conflict.partner_name}' "
                    f"with status '{blocking.status}'"
                ),
            )
            await self.db.flush()
            logger.warning(
                "Postback duplicate conflict lead_id=%s duplicate_lead_id=%s "
                "partner=%s match_type=%s",
                lead.id,
                duplicate.lead_id,
                conflict.partner_name,
                duplicate.match_type,
            )
            return

        try:
            context = self._build_template_context(lead, integration)
            payload = self.build_payload(lead, integration, context=context)
            request = self.build_request(integration, context=context)
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

        submission.request_payload = self.redact_payload(payload, integration)
        retry_config = integration.retry_config or {}
        max_attempts = int(retry_config.get("max_attempts") or 1)
        delays = [int(delay) for delay in retry_config.get("delays_seconds") or []]
        timeout_seconds = float(retry_config.get("timeout_seconds") or 30)
        request_metadata = self.request_metadata(integration, request)
        logger.info(
            "Partner request prepared integration_id=%s method=%s url=%s body_format=%s headers=%s",
            integration.id,
            request_metadata["method"],
            request_metadata["url"],
            request_metadata["body_format"],
            sorted(request["headers"]),
        )

        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await self.send_http_request(
                        client,
                        integration,
                        payload,
                        request,
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
            except httpx.ConnectError as exc:
                last_error = self._connection_error_message(integration.postback_url, exc)
                logger.warning(
                    "Postback connection failed lead_id=%s integration_id=%s "
                    "attempt=%s/%s reason=%s",
                    lead.id,
                    integration.id,
                    attempt,
                    max_attempts,
                    last_error,
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
        submission.partner_feedback = self._feedback_text(
            parsed.get("error_message")
            or parsed.get("partner_status")
            or response.text
        )
        submission.partner_status = parsed.get("partner_status")
        if submission.partner_status:
            submission.partner_status_updated_at = datetime.now(timezone.utc)
        submission.completed_at = datetime.now(timezone.utc)

        if not forced_http_failure and submission.status in {
            self.COMPLETED_STATUS,
            self.DUPLICATE_STATUS,
        }:
            local_status_code = await self._apply_partner_status_to_lead(
                lead=lead,
                integration=integration,
                partner_status=submission.partner_status or submission.status,
            )
            self._apply_validation_outcome(submission, local_status_code)
        elif (
            not forced_http_failure
            and submission.status == self.FAILED_STATUS
            and submission.partner_status
        ):
            local_status_code = await self._apply_partner_status_to_lead(
                lead=lead,
                integration=integration,
                partner_status=submission.partner_status,
            )
            self._apply_validation_outcome(submission, local_status_code)
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
    ) -> str | None:
        old_status_id = lead.status_id
        for status_code in self._lead_status_candidates(integration, partner_status):
            updated = await self.lead_repo.set_status_by_code(
                lead.id,
                lead.project_id,
                status_code,
            )
            if updated is not None:
                if old_status_id != updated.status_id:
                    await self.google_sheets_trigger.enqueue_if_status_triggered(
                        lead_id=updated.id,
                        project_id=updated.project_id,
                        status_id=updated.status_id,
                    )
                return status_code
        logger.warning(
            "Partner status could not be mapped to an existing lead status "
            "lead_id=%s partner_status=%s",
            lead.id,
            partner_status,
        )
        return None

    @staticmethod
    def _apply_validation_outcome(
        submission: LeadSubmission,
        local_status_code: str | None,
    ) -> None:
        if local_status_code == LeadStatusCode.QUALIFIED:
            submission.is_valid = True
            submission.validated_at = datetime.now(timezone.utc)
        elif local_status_code == LeadStatusCode.LOST:
            submission.is_valid = False
            submission.validated_at = datetime.now(timezone.utc)

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

    def build_request(
        self,
        integration: PartnerIntegration,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_config = getattr(integration, "request_config", None) or {}
        template_context = context or self._build_template_context(
            self._test_lead(integration),
            integration,
        )
        body_format = str(request_config.get("body_format") or "json").lower()
        method = str(request_config.get("method") or "POST").upper()
        headers = {
            "Content-Type": (
                "application/x-www-form-urlencoded"
                if body_format == "form"
                else "application/json"
            )
        }
        headers.update(
            self._render_string_mapping(request_config.get("headers") or {}, template_context)
        )
        params = self._render_string_mapping(
            request_config.get("query_params") or {},
            template_context,
        )
        auth_config = dict(integration.auth_config or {})
        token = auth_config.get("token") or integration.auth_token
        if token:
            if integration.auth_type == "bearer":
                headers["Authorization"] = f"Bearer {token}"
            elif integration.auth_type == "query_param":
                param_name = auth_config.get("query_param_name")
                if param_name:
                    params[str(param_name)] = str(token)
            elif integration.auth_type == "header":
                header_name = auth_config.get("header_name") or "Authorization"
                headers[str(header_name)] = str(token)
        return {
            "method": method,
            "body_format": body_format,
            "headers": headers,
            "params": params,
        }

    async def send_http_request(
        self,
        client: httpx.AsyncClient,
        integration: PartnerIntegration,
        payload: dict[str, Any],
        request: dict[str, Any],
    ) -> httpx.Response:
        return await client.request(
            request["method"],
            integration.postback_url,
            json=payload if request["body_format"] == "json" else None,
            data=self._form_payload(payload) if request["body_format"] == "form" else None,
            headers=request["headers"],
            params=request["params"],
        )

    def request_metadata(
        self,
        integration: PartnerIntegration,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "method": request["method"],
            "url": integration.postback_url,
            "body_format": request["body_format"],
            "headers": {
                name: self._safe_request_value(name, value, integration)
                for name, value in request["headers"].items()
            },
            "query_params": {
                name: self._safe_request_value(name, value, integration)
                for name, value in request["params"].items()
            },
        }

    @staticmethod
    def _safe_request_value(
        name: str,
        value: str,
        integration: PartnerIntegration,
    ) -> str:
        normalized_name = name.strip().lower()
        sensitive_name = any(
            marker in normalized_name
            for marker in ("authorization", "api-key", "apikey", "token", "secret")
        )
        auth_config = integration.auth_config or {}
        auth_token = auth_config.get("token") or integration.auth_token
        secret_values = {
            str(item)
            for item in (getattr(integration, "request_config", None) or {})
            .get("secret_variables", {})
            .values()
            if item not in (None, "")
        }
        if sensitive_name or (auth_token and str(auth_token) in value):
            return PostbackService._masked_credential(value)
        result = value
        for secret_value in secret_values:
            result = result.replace(secret_value, PostbackService._masked_credential(secret_value))
        return result

    @staticmethod
    def _masked_credential(value: str) -> str:
        normalized = str(value)
        suffix = normalized[-4:] if len(normalized) >= 4 else ""
        return f"***{suffix} (length={len(normalized)})"

    @staticmethod
    def _is_dns_error(exc: httpx.ConnectError) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "name or service not known",
                "nodename nor servname provided",
                "temporary failure in name resolution",
                "getaddrinfo failed",
            )
        )

    @classmethod
    def _connection_error_message(cls, url: str, exc: httpx.ConnectError) -> str:
        hostname = urlsplit(url).hostname or url
        if cls._is_dns_error(exc):
            return (
                f"DNS не может определить адрес API-домена '{hostname}'. "
                "Укажите реальный домен вместо {{host}} и проверьте DNS-запись домена."
            )
        return f"Не удалось подключиться к API-домену '{hostname}': {str(exc)[:500]}"

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

    def _build_template_context(
        self,
        lead: Lead | SimpleNamespace,
        integration: PartnerIntegration,
    ) -> dict[str, Any]:
        request_config = getattr(integration, "request_config", None) or {}
        generator_config = request_config.get("generator_config") or {}
        chat = getattr(lead, "chat", None)
        tracking = getattr(chat, "tracking_link", None) if chat is not None else None
        buyer = getattr(tracking, "buyer", None) if tracking is not None else None
        project = getattr(lead, "project", None)
        bot = getattr(chat, "bot", None) if chat is not None else None
        custom_fields = dict(getattr(lead, "custom_fields", None) or {})

        first_name, last_name = resolve_lead_names(lead)
        if not first_name:
            first_name, contact_last_name = split_lead_name(
                getattr(chat, "contact_name", None),
                username=getattr(lead, "username", None),
            )
            last_name = last_name or contact_last_name
        if not first_name:
            first_name = str(getattr(lead, "username", None) or "").removeprefix("@")
        full_name = compose_lead_name(first_name, last_name) or first_name
        last_name = last_name or first_name
        telegram_id = (
            getattr(chat, "external_user_id", None)
            or custom_fields.get("telegram_id")
            or custom_fields.get("tg_id")
        )
        phone = getattr(lead, "phone", None)
        phone_digits = re.sub(r"\D", "", str(phone or ""))
        tracking_buyer_name = getattr(tracking, "buyer_name", None) if tracking else None
        buyer_name = getattr(buyer, "name", None) or tracking_buyer_name
        tracking_code = None
        if tracking is not None:
            tracking_code = getattr(tracking, "code", None) or getattr(
                tracking,
                "ref_code",
                None,
            )
        password_length = int(generator_config.get("password_length") or 12)

        return {
            "lead": {
                "id": str(getattr(lead, "id", "")),
                "project_id": str(getattr(lead, "project_id", "")),
                "chat_id": str(getattr(lead, "chat_id", "")),
                "name": full_name,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "phone_digits": phone_digits or None,
                "username": getattr(lead, "username", None),
                "telegram_id": str(telegram_id) if telegram_id not in (None, "") else None,
                "telegram_email": (
                    f"tg{telegram_id}@lead.auto"
                    if telegram_id not in (None, "")
                    else None
                ),
                "age": getattr(lead, "age", None),
                "country": getattr(lead, "country", None),
                "call_time": (
                    getattr(lead, "preferred_call_time", None)
                    or getattr(lead, "call_time_text", None)
                ),
                "manager_comment": getattr(lead, "manager_comment", None),
                "has_card": getattr(lead, "has_card", None),
                "score_percent": getattr(lead, "score_percent", None),
                "created_at": self._json_safe(getattr(lead, "created_at", None)),
                "custom": custom_fields,
            },
            "custom": custom_fields,
            "tracking": {
                "id": str(getattr(tracking, "id", "")) if tracking else None,
                "code": tracking_code,
                "ref_code": getattr(tracking, "ref_code", None) if tracking else None,
                "title": getattr(tracking, "title", None) if tracking else None,
                "buyer_name": buyer_name,
            },
            "buyer": {
                "id": str(getattr(buyer, "id", "")) if buyer else None,
                "name": buyer_name,
                "email": getattr(buyer, "email", None) if buyer else None,
                "telegram_id": getattr(buyer, "buyer_telegram_id", None) if buyer else None,
            },
            "project": {
                "id": str(getattr(lead, "project_id", "")),
                "name": getattr(project, "name", None) if project else None,
            },
            "bot": {
                "id": str(getattr(bot, "id", "")) if bot else None,
                "name": getattr(bot, "name", None) if bot else None,
                "username": getattr(bot, "bot_username", None) if bot else None,
            },
            "secret": dict(request_config.get("secret_variables") or {}),
            "random": {
                "password": self._generate_password(password_length),
                "ipv4": self._generate_ipv4(generator_config.get("ipv4_cidrs") or []),
            },
        }

    def _render_template_value(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._render_template_value(item, context)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._render_template_value(item, context) for item in value]
        if not isinstance(value, str):
            return self._json_safe(value)

        full_match = self.FULL_TEMPLATE_PATTERN.match(value)
        if full_match:
            placeholder = full_match.group(1)
            resolved = self._get_path_value(context, placeholder)
            self._validate_required_placeholder(placeholder, resolved)
            return self._json_safe(resolved)

        def replace(match: re.Match[str]) -> str:
            placeholder = match.group(1)
            resolved = self._get_path_value(context, placeholder)
            self._validate_required_placeholder(placeholder, resolved)
            return "" if resolved is None else str(resolved)

        return self.TEMPLATE_PATTERN.sub(replace, value)

    @staticmethod
    def _validate_required_placeholder(placeholder: str, value: Any) -> None:
        if value not in (None, ""):
            return
        if placeholder.startswith("secret."):
            secret_name = placeholder.removeprefix("secret.")
            raise ValueError(
                f"Не заполнена секретная переменная партнёра '{secret_name}'"
            )
        if placeholder == "random.ipv4":
            raise ValueError(
                "Не настроен IPv4 CIDR pool для генерации IP партнёрского запроса"
            )

    def _render_string_mapping(
        self,
        mapping: dict[str, str],
        context: dict[str, Any],
    ) -> dict[str, str]:
        rendered: dict[str, str] = {}
        for key, template in mapping.items():
            value = self._render_template_value(template, context)
            if value is not None:
                rendered[str(key)] = str(value)
        return rendered

    @classmethod
    def _omit_null_dict_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            if isinstance(item, dict):
                result[key] = cls._omit_null_dict_values(item)
            elif isinstance(item, list):
                result[key] = [
                    cls._omit_null_dict_values(element)
                    if isinstance(element, dict)
                    else element
                    for element in item
                    if element is not None
                ]
            else:
                result[key] = item
        return result

    @staticmethod
    def _generate_password(length: int) -> str:
        safe_length = min(max(length, 8), 64)
        required = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
        ]
        alphabet = string.ascii_letters + string.digits
        characters = required + [
            secrets.choice(alphabet) for _ in range(safe_length - len(required))
        ]
        secrets.SystemRandom().shuffle(characters)
        return "".join(characters)

    @staticmethod
    def _generate_ipv4(cidrs: list[str]) -> str | None:
        if not cidrs:
            return None
        network = ipaddress.IPv4Network(secrets.choice(cidrs), strict=False)
        has_reserved_edges = network.num_addresses > 2
        first = int(network.network_address) + (1 if has_reserved_edges else 0)
        last = int(network.broadcast_address) - (1 if has_reserved_edges else 0)
        return str(ipaddress.IPv4Address(first + secrets.randbelow(last - first + 1)))

    @staticmethod
    def _form_payload(payload: dict[str, Any]) -> dict[str, str]:
        form: dict[str, str] = {}
        for key, value in payload.items():
            if value is None:
                form[str(key)] = ""
            elif isinstance(value, (dict, list)):
                form[str(key)] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, bool):
                form[str(key)] = "true" if value else "false"
            else:
                form[str(key)] = str(value)
        return form

    @staticmethod
    def _default_lead_payload(lead: Lead) -> dict[str, Any]:
        return {
            "lead_id": str(lead.id),
            "name": lead.name,
            "phone": lead.phone,
            "username": lead.username,
            "age": lead.age,
            "country": lead.country,
            "call_time": lead.preferred_call_time or lead.call_time_text,
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
            manager_comment="Test manager comment",
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
        submission.partner_feedback = error[:2000]
        submission.completed_at = datetime.now(timezone.utc)

    @staticmethod
    def _feedback_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:2000] if text else None
