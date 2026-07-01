from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.core.constants import TrackingCostModel


def calculate_tracking_spend(
    *,
    cost_model: TrackingCostModel | str,
    price_per_unit: Decimal,
    manual_spend: Decimal,
    starts: int,
    submitted_leads: int,
) -> Decimal:
    model = TrackingCostModel(cost_model)
    price = Decimal(price_per_unit or 0)
    manual = Decimal(manual_spend or 0)

    if model == TrackingCostModel.FIX_PDP:
        value = Decimal(starts) * price
    elif model == TrackingCostModel.CPA:
        value = Decimal(submitted_leads) * price
    else:
        value = manual

    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
