from decimal import Decimal
import unittest

from app.services.tracking_metrics_service import TrackingMetricsService


class TrackingBreakdownTests(unittest.TestCase):
    def test_build_breakdown_calculates_percentages_with_unknown_values(self) -> None:
        items = TrackingMetricsService._build_breakdown(
            [
                {"key": "25_34", "label": "25–34", "count": 3},
                {"key": "unknown", "label": "Не указан", "count": 1},
            ]
        )

        self.assertEqual([item.count for item in items], [3, 1])
        self.assertEqual(items[0].percent, Decimal("75.00"))
        self.assertEqual(items[1].percent, Decimal("25.00"))

    def test_build_breakdown_handles_empty_counts(self) -> None:
        items = TrackingMetricsService._build_breakdown(
            [{"key": "unknown", "label": "Не указано", "count": 0}]
        )

        self.assertEqual(items[0].percent, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
