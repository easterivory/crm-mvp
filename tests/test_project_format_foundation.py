from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.core.constants import RoleName, SenderType
from app.schemas.partner import LeadSubmissionOut
from app.services.chat_service import ChatService
from app.services.lead_confidence_service import ConfidenceContext, LeadConfidenceService
from app.services.manager_analytics_service import ManagerAnalyticsService
from app.services.partner_service import PartnerService
from app.services.postback_endpoint_service import PostbackEndpointService


class _AsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class ConfidenceBackwardCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _service(*, lead, chat, project, applicable_fields=frozenset()):
        service = LeadConfidenceService.__new__(LeadConfidenceService)
        service._load_context = AsyncMock(
            return_value=ConfidenceContext(
                lead=lead,
                chat=chat,
                project=project,
                applicable_fields=applicable_fields,
                minimum_amount=None,
                reask_count=0,
                max_answer_pause_hours=None,
                broadcast_followup=False,
            )
        )
        service.identity = SimpleNamespace(
            normalize_phone=lambda value: None,
            find_duplicates=AsyncMock(return_value=[]),
        )
        return service

    async def test_unasked_optional_fields_do_not_reduce_existing_funnel_score(self) -> None:
        lead = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            chat_id=uuid4(),
            name="Анна",
            phone=None,
            country=None,
            has_card=None,
            custom_fields={},
        )
        project = SimpleNamespace(
            use_confidence_score=True,
            confidence_weights=None,
            confidence_thresholds=None,
            vip_tags=[],
        )
        service = self._service(
            lead=lead,
            chat=SimpleNamespace(tracking_link_id=uuid4()),
            project=project,
        )

        result = await service.calculate_confidence(lead)

        self.assertEqual(result.score_percent, 100)
        self.assertEqual(result.reasons, [])
        self.assertFalse(result.meta["checks"]["card_status"]["applicable"])
        self.assertFalse(result.meta["checks"]["start_amount"]["applicable"])

    async def test_city_and_country_conflict_sets_iso_meta_and_project_penalty(self) -> None:
        lead = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            chat_id=uuid4(),
            name="Анна",
            phone=None,
            country="Россия",
            has_card=None,
            custom_fields={"city": "Алматы"},
        )
        project = SimpleNamespace(
            use_confidence_score=True,
            confidence_weights={"geo_conflict": 7},
            confidence_thresholds=None,
            vip_tags=[],
        )
        service = self._service(
            lead=lead,
            chat=SimpleNamespace(tracking_link_id=uuid4()),
            project=project,
            applicable_fields=frozenset({"country", "city"}),
        )

        result = await service.calculate_confidence(lead)

        self.assertEqual(result.score_percent, 93)
        self.assertEqual(result.meta["country_code"], "RU")
        self.assertTrue(result.meta["geo_conflict"])
        self.assertEqual(result.reasons[0]["code"], "geo")


class LeaseAndSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_incoming_message_renews_existing_assignment(self) -> None:
        chat_id = uuid4()
        project_id = uuid4()
        now = datetime.now(timezone.utc)
        service = ChatService.__new__(ChatService)
        service.chat_repo = SimpleNamespace(
            update_timestamps=AsyncMock(),
            get_by_id=AsyncMock(return_value=SimpleNamespace(project_id=project_id)),
        )
        service.chat_lease = SimpleNamespace(
            renew_from_client_message=AsyncMock(return_value=True),
        )

        await service.update_timestamps(chat_id, SenderType.USER, now)

        service.chat_lease.renew_from_client_message.assert_awaited_once_with(
            project_id=project_id,
            chat_id=chat_id,
        )

    async def test_manual_submission_clears_previous_manual_required_decision(self) -> None:
        project_id = uuid4()
        lead = SimpleNamespace(id=uuid4())
        integration = SimpleNamespace(id=uuid4(), is_active=True)
        actor = SimpleNamespace(id=uuid4(), role_name=RoleName.MANAGER)
        submission = SimpleNamespace(id=uuid4())
        service = PartnerService.__new__(PartnerService)
        service.db = SimpleNamespace(begin_nested=lambda: _AsyncContext())
        service.repo = SimpleNamespace(
            get_lead_in_project=AsyncMock(return_value=lead),
            list_submissions_for_lead_partner=AsyncMock(return_value=[]),
            create_submission=AsyncMock(return_value=submission),
            clear_manual_required_decision=AsyncMock(),
        )
        service._ensure_can_submit = MagicMock()
        service._ensure_project_access = MagicMock()
        service._get_or_404 = AsyncMock(return_value=integration)

        output = SimpleNamespace(id=submission.id)
        with patch.object(LeadSubmissionOut, "model_validate", return_value=output):
            result = await service.queue_lead_submission(
                lead_id=lead.id,
                partner_integration_id=integration.id,
                project_id=project_id,
                actor=actor,
            )

        self.assertIs(result, output)
        service.repo.clear_manual_required_decision.assert_awaited_once_with(
            lead_id=lead.id,
            partner_integration_id=integration.id,
        )


class PostbackFoundationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _service(endpoint):
        db = SimpleNamespace()
        db.scalar = AsyncMock(return_value=endpoint)
        db.add = MagicMock()

        async def flush() -> None:
            instance = db.add.call_args.args[0]
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()

        db.flush = AsyncMock(side_effect=flush)
        service = PostbackEndpointService(db)
        return service, db

    async def test_missing_identifier_is_saved_as_unmatched_receipt(self) -> None:
        endpoint = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            partner_integration_id=None,
            event_type="registration",
            parameter_mapping={
                "identifier_type": "lead_id",
                "identifier_param": "lead_id",
            },
        )
        service, db = self._service(endpoint)
        service._match_lead = AsyncMock(return_value=None)

        result = await service.receive(
            secret_token="valid-secret",
            request_method="GET",
            query_payload={},
            body_payload={},
        )

        receipt = db.add.call_args.args[0]
        self.assertEqual(result.status, "unmatched")
        self.assertEqual(receipt.status, "unmatched")
        self.assertIn("lead_id", receipt.error_message)

    async def test_external_event_id_returns_duplicate_without_second_event(self) -> None:
        endpoint = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            partner_integration_id=uuid4(),
            event_type="deposit",
            parameter_mapping={
                "identifier_type": "external_id",
                "identifier_param": "payload.lead",
                "amount_param": "payload.amount",
                "currency_param": "payload.currency",
                "external_event_id_param": "payload.event_id",
            },
        )
        lead = SimpleNamespace(id=uuid4())
        event = SimpleNamespace(id=uuid4())
        service, db = self._service(endpoint)
        service._match_lead = AsyncMock(return_value=lead)
        service.events = SimpleNamespace(
            record_event=AsyncMock(return_value=(event, False)),
        )

        result = await service.receive(
            secret_token="valid-secret",
            request_method="POST",
            query_payload={},
            body_payload={
                "payload": {
                    "lead": "partner-42",
                    "amount": "125,50",
                    "currency": "usd",
                    "event_id": "evt-1",
                }
            },
        )

        receipt = db.add.call_args.args[0]
        self.assertEqual(result.status, "duplicate")
        self.assertEqual(receipt.status, "duplicate")
        call = service.events.record_event.await_args.kwargs
        self.assertEqual(call["amount"], Decimal("125.50"))
        self.assertEqual(call["external_event_id"], "evt-1")


class ManagerAnalyticsContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_retained_query_excludes_lease_expired_assignments(self) -> None:
        empty_mappings = SimpleNamespace(all=lambda: [])
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(mappings=lambda: empty_mappings),
            )
        )

        result = await ManagerAnalyticsService(db).get_project_performance(
            project_id=uuid4(),
        )

        self.assertEqual(result, [])
        statement = db.execute.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("chat_lease_expired", sql)
        self.assertIn("NOT (EXISTS", sql)
        self.assertIn("lead.manager_assigned", sql)


if __name__ == "__main__":
    unittest.main()
