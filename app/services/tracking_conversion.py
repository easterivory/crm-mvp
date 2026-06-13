"""Conversion benchmark helpers for tracking links."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.core.constants import TrackingConversionStatus


def calculate_conversion_status(
    *,
    clicks: int,
    starts: int,
    leads: int,
    base_conversion_rate: float,
    min_sample_size: int,
) -> TrackingConversionStatus:
    sample_size = _effective_sample_size(clicks=clicks, starts=starts)
    if sample_size < min_sample_size:
        return TrackingConversionStatus.INSUFFICIENT_DATA

    conversion_rate = _ratio_percent(leads, sample_size)
    target_rate = Decimal(str(base_conversion_rate))
    if conversion_rate >= target_rate * Decimal("1.2"):
        return TrackingConversionStatus.HIGH_CR
    if conversion_rate <= target_rate * Decimal("0.7"):
        return TrackingConversionStatus.LOW_CR
    return TrackingConversionStatus.NORMAL_CR


def _effective_sample_size(*, clicks: int, starts: int) -> int:
    return max(clicks, 0) if clicks > 0 else max(starts, 0)


def _ratio_percent(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.00")
    return (
        Decimal(max(numerator, 0)) / Decimal(denominator) * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
