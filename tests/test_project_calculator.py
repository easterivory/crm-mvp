from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api import spa
from app.api.v1.routers import analytics
from app.core.constants import RoleName
from app.schemas.tracking_metrics import TrackingMetricSummary


class ProjectCalculatorAccessTests(unittest.TestCase):
    def test_calculator_has_direct_spa_route(self) -> None:
        route_paths = {route.path for route in spa.router.routes}
        self.assertIn("/calculator", route_paths)

    def test_only_admin_roles_can_open_calculator(self) -> None:
        analytics._ensure_admin(SimpleNamespace(role_name=RoleName.ADMIN))
        analytics._ensure_admin(SimpleNamespace(role_name=RoleName.SUPER_ADMIN))

        for role in (RoleName.MANAGER, RoleName.BUYER, RoleName.OPERATOR):
            with self.assertRaises(HTTPException) as raised:
                analytics._ensure_admin(SimpleNamespace(role_name=role))
            self.assertEqual(raised.exception.status_code, 403)


class ProjectCalculatorSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_uses_canonical_tracking_summary(self) -> None:
        project_id = uuid4()
        tracking_service = SimpleNamespace(
            get_project_metrics=AsyncMock(
                return_value=SimpleNamespace(
                    project_format="gambling",
                    bot_id=None,
                    date_from=date(2026, 8, 1),
                    date_to=date(2026, 8, 25),
                    summary=TrackingMetricSummary(
                        clicks=120,
                        starts=74,
                        leads=31,
                        registrations=18,
                        first_deposits=7,
                        redeposits=3,
                        channel_join_requests=14,
                        channel_joins=11,
                        spend=Decimal("245.50"),
                    ),
                )
            )
        )
        project_repository = SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(name="Casino Project"))
        )
        actor = SimpleNamespace(role_name=RoleName.ADMIN)

        with (
            patch.object(
                analytics,
                "TrackingMetricsService",
                return_value=tracking_service,
            ),
            patch.object(
                analytics,
                "ProjectRepository",
                return_value=project_repository,
            ),
        ):
            result = await analytics.get_project_calculator_snapshot(
                bot_id=None,
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 25),
                project_id=project_id,
                current_user=actor,
                db=AsyncMock(),
            )

        self.assertEqual(result.project_id, project_id)
        self.assertEqual(result.project_name, "Casino Project")
        self.assertEqual(result.project_format, "gambling")
        self.assertEqual(result.registrations, 18)
        self.assertEqual(result.first_deposits, 7)
        self.assertEqual(result.redeposits, 3)
        self.assertEqual(result.channel_joins, 11)
        self.assertEqual(result.spend, Decimal("245.50"))
        tracking_service.get_project_metrics.assert_awaited_once_with(
            current_user=actor,
            project_id=project_id,
            bot_id=None,
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 25),
        )
