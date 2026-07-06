import unittest

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.lead import Lead
from app.models.user import User
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import LeadUpdate
from app.services.buyer_analytics_service import BuyerAnalyticsService


class LeadPartialUpdateTests(unittest.TestCase):
    def test_single_name_field_is_a_valid_partial_update(self) -> None:
        update = LeadUpdate(first_name="Анна")

        self.assertEqual(update.model_fields_set, {"first_name"})
        self.assertEqual(update.model_dump(exclude_unset=True), {"first_name": "Анна"})


class LeadSubmissionFilterTests(unittest.TestCase):
    def test_active_filter_excludes_successful_submissions(self) -> None:
        statement = LeadRepository._apply_submission_state(select(Lead), "active")
        sql = str(statement.compile(dialect=postgresql.dialect()))

        self.assertIn("NOT (EXISTS", sql)
        self.assertIn("lead_submissions", sql)

    def test_completed_funnel_filter_requires_completed_runtime(self) -> None:
        statement = LeadRepository._apply_funnel_completed(select(Lead), True)
        sql = str(statement.compile(dialect=postgresql.dialect()))

        self.assertIn("chat_funnel_states", sql)
        self.assertIn("completed_at IS NOT NULL", sql)

    def test_submitted_filter_requires_successful_submission(self) -> None:
        statement = LeadRepository._apply_submission_state(select(Lead), "submitted")
        sql = str(statement.compile(dialect=postgresql.dialect()))

        self.assertIn("EXISTS", sql)
        self.assertNotIn("NOT (EXISTS", sql)
        self.assertIn("lead_submissions", sql)


class BuyerAnalyticsRoleTests(unittest.TestCase):
    def test_buyer_analytics_accepts_manager_and_buyer_roles(self) -> None:
        statement = select(User).where(
            BuyerAnalyticsService._buyer_account_filter(User.id)
        )
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("manager", sql)
        self.assertIn("buyer", sql)


if __name__ == "__main__":
    unittest.main()
