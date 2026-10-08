from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIBudgetReservation, AIProjectSettings, AIUsageLog
from app.services.ai_gateway_service import AIGatewayError, AIProviderSnapshot


class AIBudgetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def request_reserve(
        connection: AIProviderSnapshot,
        model: str,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
    ) -> Decimal:
        price = connection.pricing_json.get(model)
        try:
            input_price = Decimal(str(price["input_usd_per_million"]))
            output_price = Decimal(str(price["output_usd_per_million"]))
            if not all(
                value.is_finite() and value >= 0
                for value in (input_price, output_price)
            ):
                raise ValueError("Invalid price")
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise AIGatewayError(
                "Valid model prices are required for budget enforcement",
                code="model_pricing_required",
            ) from exc
        # Conservative byte-based allowance, including protocol overhead. Actual billing
        # is reconciled from provider usage, not from this pre-flight estimate.
        input_allowance = (
            len(system_prompt.encode("utf-8"))
            + 1024
            + sum(
                len(item.get("content", "").encode("utf-8")) + 128 for item in messages
            )
        )
        return (
            (input_allowance * input_price + max_output_tokens * output_price)
            / Decimal(1_000_000)
        ).quantize(Decimal("0.00000001"), rounding=ROUND_UP)

    async def reserve(
        self, project_id: UUID, amount: Decimal
    ) -> AIBudgetReservation | None:
        policy = (
            await self.db.execute(
                select(AIProjectSettings)
                .where(AIProjectSettings.project_id == project_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if policy is None or not policy.is_enabled:
            raise AIGatewayError("AI is disabled for this project", code="ai_disabled")
        if policy.daily_budget_usd is None and policy.monthly_budget_usd is None:
            return None
        now = datetime.now(timezone.utc)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for start, limit, label in (
            (day, policy.daily_budget_usd, "Daily"),
            (day.replace(day=1), policy.monthly_budget_usd, "Monthly"),
        ):
            if (
                limit is not None
                and await self.allocated(project_id, start) + amount > limit
            ):
                raise AIGatewayError(
                    f"{label} AI budget cannot cover this request",
                    code="ai_budget_exceeded",
                )
        reservation = AIBudgetReservation(
            project_id=project_id, amount_usd=amount, settled=False
        )
        self.db.add(reservation)
        await self.db.flush()
        return reservation

    async def allocated(self, project_id: UUID, start: datetime) -> Decimal:
        spent = (
            select(func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0))
            .where(AIUsageLog.project_id == project_id, AIUsageLog.created_at >= start)
            .scalar_subquery()
        )
        reserved = (
            select(func.coalesce(func.sum(AIBudgetReservation.amount_usd), 0))
            .where(
                AIBudgetReservation.project_id == project_id,
                AIBudgetReservation.created_at >= start,
                AIBudgetReservation.settled.is_(False),
            )
            .scalar_subquery()
        )
        # One MVCC snapshot: settlement must not disappear between reading
        # confirmed spend and outstanding reservations.
        return Decimal((await self.db.execute(select(spent + reserved))).scalar_one())
