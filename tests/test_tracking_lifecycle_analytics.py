from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.services.lead_event_service import LeadEventService
from app.services.tracking_metrics_service import TrackingMetricsService


def _postgres_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_submission_metrics_use_first_successful_submission_record() -> None:
    submissions = TrackingMetricsRepository._first_successful_submissions()
    sql = _postgres_sql(select(submissions))

    assert "lead_submissions" in sql
    assert "row_number()" in sql
    assert "success" in sql
    assert "completed" in sql
    assert "coalesce(lead_submissions.completed_at, lead_submissions.submitted_at)" in sql
    assert "lead_statuses" not in sql


def test_lifecycle_metrics_dedupe_registration_and_first_deposit() -> None:
    events = LifecycleMetricsRepository._eligible_events(uuid4())
    sql = _postgres_sql(select(events))

    assert "row_number()" in sql
    assert "registration" in sql
    assert "first_deposit" in sql
    assert "redeposit" in sql
    assert "milestone_number = 1" in sql


def test_event_aliases_are_normalized_before_storage() -> None:
    assert LeadEventService.normalize_event_type("REG") == "registration"
    assert LeadEventService.normalize_event_type("first_deposit") == "deposit"
    assert LeadEventService.normalize_event_type("FD") == "deposit"
    assert LeadEventService.normalize_event_type("RD") == "redeposit"
    assert LeadEventService.normalize_event_type("custom_event") == "custom_event"


def test_gambling_summary_exposes_independent_conversion_chain() -> None:
    summary = TrackingMetricsService._summary_from_values(
        {
            "clicks": 20,
            "starts": 10,
            "leads": 8,
            "submitted_leads": 0,
            "registrations": 6,
            "first_deposits": 3,
            "redeposits": 2,
            "spend": Decimal("120"),
        }
    )

    assert summary.registrations == 6
    assert summary.first_deposits == 3
    assert summary.deposits == 3
    assert summary.redeposits == 2
    assert summary.cr_to_registration == Decimal("60.00")
    assert summary.cr_registration_to_deposit == Decimal("50.00")
    assert summary.cpfd == Decimal("40.00")


def test_daily_merge_hides_submissions_only_for_gambling_view() -> None:
    rows = [
        {
            "date": date(2026, 7, 28),
            "starts": 4,
            "leads": 3,
            "submitted_leads": 2,
            "spend": Decimal("10"),
        }
    ]
    lifecycle = [
        {
            "date": date(2026, 7, 28),
            "registrations": 2,
            "first_deposits": 1,
            "redeposits": 1,
        }
    ]

    gambling = TrackingMetricsService._merge_lifecycle_daily(
        rows,
        lifecycle,
        hide_submissions=True,
    )
    submission = TrackingMetricsService._merge_lifecycle_daily(
        rows,
        lifecycle,
        hide_submissions=False,
    )

    assert gambling[0]["submitted_leads"] == 0
    assert gambling[0]["first_deposits"] == 1
    assert submission[0]["submitted_leads"] == 2


def test_lifecycle_repository_queries_all_sources() -> None:
    repository = LifecycleMetricsRepository(AsyncMock())
    events = repository._eligible_events(uuid4())
    sql = _postgres_sql(select(events))

    assert "source" in sql
    assert "postback_endpoint_id" not in sql
    assert "created_by_user_id" not in sql
