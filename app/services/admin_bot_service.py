"""Administrator Telegram bot, project summaries, and proactive alerts."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import RoleName, TrackingConversionStatus
from app.models.lead import Lead
from app.models.partner import LeadSubmission
from app.models.project import Project
from app.models.role import Role
from app.models.tracking_alert import TrackingConversionAlertState
from app.models.user import User, UserProjectAccess
from app.repositories.project_metrics_repository import ProjectMetricsRepository
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.services.access_control import accessible_project_ids
from app.services.system_setting_service import SystemSettingService
from app.services.tracking_conversion import calculate_conversion_status

logger = logging.getLogger(__name__)


class AdminTelegramClient:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = httpx.AsyncClient(timeout=35.0)

    async def get_updates(self, offset: int | None = None, timeout_seconds: int = 25) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout_seconds, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        data = await self._post("getUpdates", payload)
        result = data.get("result")
        return result if isinstance(result, list) else []

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._post(
            "sendMessage",
            {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True},
        )

    async def set_commands(self) -> None:
        await self._post(
            "setMyCommands",
            {"commands": [{"command": "stats", "description": "Статистика по проектам"}]},
        )

    async def close(self) -> None:
        await self.session.aclose()

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.session.post(f"{self.base_url}/{method}", json=payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Telegram {method} returned non-JSON response") from exc
        if response.status_code >= 400 or data.get("ok") is not True:
            raise RuntimeError(
                f"Telegram {method} failed: {data.get('description') or response.text[:500]}"
            )
        return data


class AdminBotService:
    def __init__(self, db: AsyncSession, telegram: AdminTelegramClient) -> None:
        self.db = db
        self.telegram = telegram

    async def handle_update(self, raw_update: dict[str, Any]) -> None:
        message = raw_update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
            return
        chat_id = int(chat["id"])
        text = str(message.get("text") or "").strip()
        user = await self._get_admin(chat_id)
        if user is None:
            await self.telegram.send_message(
                chat_id,
                "Доступ запрещён. Укажи этот Telegram ID в профиле администратора CRM.",
            )
            return
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if command in {"/start", "/stats"}:
            await self.telegram.send_message(chat_id, await self._build_stats(user))
            return
        await self.telegram.send_message(chat_id, "Используй /stats для сводки по проектам.")

    async def _get_admin(self, telegram_id: int) -> User | None:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.role), selectinload(User.project_accesses))
            .where(
                User.telegram_id == telegram_id,
                User.is_deleted.is_(False),
                User.role.has(Role.name.in_((RoleName.ADMIN, RoleName.SUPER_ADMIN))),
            )
        )
        return result.scalar_one_or_none()

    async def _build_stats(self, user: User) -> str:
        stmt = select(Project).where(Project.is_deleted.is_(False), Project.status == "active")
        if user.role_name != RoleName.SUPER_ADMIN:
            project_ids = accessible_project_ids(user)
            if not project_ids:
                return "У аккаунта нет доступных активных проектов."
            stmt = stmt.where(Project.id.in_(project_ids))
        projects = list((await self.db.execute(stmt.order_by(Project.name.asc()))).scalars().all())
        if not projects:
            return "Активные проекты не найдены."

        metrics_repo = ProjectMetricsRepository(self.db)
        lines = [f"Сводка за {date.today().isoformat()}:"]
        for project in projects:
            metrics = await metrics_repo.header_metrics(project.id, date.today())
            income = await self._project_income(project.id, date.today())
            lines.append(
                f"{project.name}\n"
                f"Трафик: {metrics['subscribers_today']} | Лиды: {metrics['leads_today']}\n"
                f"Доход: ${income} | Расход: ${_money(metrics['spend_today'])}"
            )
        return "\n\n".join(lines)

    async def _project_income(self, project_id: UUID, day: date) -> Decimal:
        start_at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)
        result = await self.db.execute(
            select(LeadSubmission.response_payload)
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                LeadSubmission.status.in_(("success", "completed", "duplicate")),
                LeadSubmission.completed_at >= start_at,
                LeadSubmission.completed_at < end_at,
            )
        )
        total = Decimal("0")
        for payload in result.scalars().all():
            amount = _extract_revenue_amount(payload)
            if amount is not None:
                total += amount
        return _money(total)


class LowConversionAdminAlertService:
    """Detect benchmark transitions and notify project admins exactly on entry to low_cr."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.metrics_repo = TrackingMetricsRepository(db)

    async def check_project(self, project: Project) -> int:
        today = date.today()
        rows = await self.metrics_repo.get_link_metrics_rows(
            project_id=project.id,
            bot_id=None,
            date_from=today - timedelta(days=29),
            date_to=today,
            lead_status_codes=tuple(project.tracking_lead_status_codes),
        )
        sent_count = 0
        for row in rows:
            status = calculate_conversion_status(
                clicks=int(row["clicks"] or 0),
                starts=int(row["starts"] or 0),
                leads=int(row["leads"] or 0),
                base_conversion_rate=float(row["base_conversion_rate"]),
                min_sample_size=int(row["min_sample_size"]),
            )
            state = await self.db.get(TrackingConversionAlertState, row["link_id"])
            previous_status = state.last_status if state is not None else None
            if status == TrackingConversionStatus.LOW_CR and previous_status != status.value:
                delivered = await self._send_low_cr_alert(project.id, row)
                if delivered == 0:
                    continue
                sent_count += delivered
                alerted_at = datetime.now(timezone.utc)
            else:
                alerted_at = state.low_cr_alerted_at if state is not None else None

            if state is None:
                self.db.add(
                    TrackingConversionAlertState(
                        tracking_link_id=row["link_id"],
                        last_status=status.value,
                        low_cr_alerted_at=alerted_at,
                    )
                )
            else:
                state.last_status = status.value
                state.low_cr_alerted_at = alerted_at
        await self.db.flush()
        return sent_count

    async def _send_low_cr_alert(self, project_id: UUID, row: dict[str, Any]) -> int:
        token = (await SystemSettingService(self.db).get_effective_global_config()).admin_bot_token
        if not token:
            return 0
        recipients = await self._project_admin_chat_ids(project_id)
        if not recipients:
            return 0
        clicks = int(row["clicks"] or 0)
        starts = int(row["starts"] or 0)
        leads = int(row["leads"] or 0)
        sample = clicks if clicks > 0 else starts
        spend = Decimal(row["spend"] or 0)
        cpl = _money(spend / Decimal(leads)) if leads > 0 else Decimal("0.00")
        cr = _percent(Decimal(leads) / Decimal(sample) * Decimal("100")) if sample else Decimal("0.0")
        buyer_name = str(row.get("buyer_name") or "не указан")
        text = (
            f"⚠️ Внимание! Ссылка {row['title']} баера {buyer_name} имеет низкий конверт "
            f"(CPL: ${cpl}, CR: {cr}%). Рекомендуется остановить трафик."
        )
        client = AdminTelegramClient(token)
        delivered = 0
        try:
            for chat_id in recipients:
                try:
                    await client.send_message(chat_id, text)
                    delivered += 1
                except Exception:
                    logger.exception("Could not deliver low_cr alert to admin chat_id=%s", chat_id)
        finally:
            await client.close()
        return delivered

    async def _project_admin_chat_ids(self, project_id: UUID) -> list[int]:
        result = await self.db.execute(
            select(User.telegram_id)
            .join(Role, Role.id == User.role_id)
            .where(
                User.telegram_id.is_not(None),
                User.is_deleted.is_(False),
                or_(
                    Role.name == RoleName.SUPER_ADMIN,
                    (
                        (Role.name == RoleName.ADMIN)
                        & or_(
                            User.project_id == project_id,
                            User.id.in_(
                                select(UserProjectAccess.user_id).where(
                                    UserProjectAccess.project_id == project_id
                                )
                            ),
                        )
                    ),
                ),
            )
            .distinct()
        )
        return [int(value) for value in result.scalars().all() if value is not None]


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _extract_revenue_amount(payload: Any) -> Decimal | None:
    """Read a partner-provided monetary value without assuming one response schema."""
    if not isinstance(payload, dict):
        return None
    revenue_keys = ("revenue", "payout", "income", "amount", "deposit")
    for key in revenue_keys:
        if key not in payload:
            continue
        parsed = _decimal_or_none(payload[key])
        if parsed is not None:
            return parsed
    for value in payload.values():
        if isinstance(value, dict):
            parsed = _extract_revenue_amount(value)
            if parsed is not None:
                return parsed
        elif isinstance(value, list):
            for item in value:
                parsed = _extract_revenue_amount(item)
                if parsed is not None:
                    return parsed
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    normalized = str(value).strip().replace("$", "").replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None
