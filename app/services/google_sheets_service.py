from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.chat import Chat
from app.models.google_sheets import ProjectGoogleSheetsConfig
from app.models.lead import Lead
from app.models.tracking import TrackingLink, TrackingSpend

logger = logging.getLogger(__name__)

GOOGLE_SHEETS_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
LEAD_EXPORT_HEADER = [
    "Дата создания",
    "Имя",
    "Телефон",
    "Telegram",
    "Страна",
    "Возраст",
    "Ссылка",
    "Баер",
    "Статус",
    "CPL ($)",
    "Уверенность (%)",
]


class GoogleSheetsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def export_lead_to_sheet(self, lead_id: UUID, project_id: UUID) -> None:
        config = await self._get_config(project_id)
        if not self._can_export(config):
            return

        lead = await self._get_lead_for_export(lead_id=lead_id, project_id=project_id)
        if lead is None:
            logger.warning(
                "Google Sheets export skipped: lead not found lead_id=%s project_id=%s",
                lead_id,
                project_id,
            )
            return

        try:
            worksheet = await self._get_or_create_worksheet(config)
            await asyncio.to_thread(
                worksheet.append_row,
                await self._build_lead_row(lead),
                value_input_option="USER_ENTERED",
            )
        except APIError as exc:
            logger.warning(
                "Google Sheets API export failed lead_id=%s project_id=%s spreadsheet_id=%s "
                "service_account_email=%s error=%s",
                lead_id,
                project_id,
                config.spreadsheet_id,
                settings.GOOGLE_SERVICE_ACCOUNT_EMAIL,
                exc,
            )
        except SpreadsheetNotFound as exc:
            logger.warning(
                "Google Sheets spreadsheet is not accessible lead_id=%s project_id=%s "
                "spreadsheet_id=%s service_account_email=%s error=%s",
                lead_id,
                project_id,
                config.spreadsheet_id,
                settings.GOOGLE_SERVICE_ACCOUNT_EMAIL,
                exc,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Google Sheets export skipped due to invalid service account config "
                "lead_id=%s project_id=%s error=%s",
                lead_id,
                project_id,
                exc,
            )

    async def test_connection(self, project_id: UUID) -> bool:
        result = await self.test_connection_result(project_id)
        return result[0]

    async def test_connection_result(self, project_id: UUID) -> tuple[bool, str]:
        config = await self._get_config(project_id)
        if config is None or not config.spreadsheet_id:
            return False, "Google Sheets integration is not configured"

        try:
            worksheet = await self._get_or_create_worksheet(config)
            await asyncio.to_thread(
                worksheet.append_row,
                [
                    "ТЕСТ ПОДКЛЮЧЕНИЯ CRM",
                    "Соединение успешно!",
                    f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                ],
                value_input_option="USER_ENTERED",
            )
            return True, "Тестовая строка успешно добавлена в таблицу!"
        except (APIError, SpreadsheetNotFound) as exc:
            logger.warning(
                "Google Sheets test connection failed project_id=%s spreadsheet_id=%s "
                "service_account_email=%s error=%s",
                project_id,
                config.spreadsheet_id,
                settings.GOOGLE_SERVICE_ACCOUNT_EMAIL,
                exc,
            )
            return False, str(exc)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Google Sheets test connection skipped due to invalid service account config "
                "project_id=%s error=%s",
                project_id,
                exc,
            )
            return False, str(exc)

    async def _get_config(
        self,
        project_id: UUID,
    ) -> ProjectGoogleSheetsConfig | None:
        result = await self.db.execute(
            select(ProjectGoogleSheetsConfig).where(
                ProjectGoogleSheetsConfig.project_id == project_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _can_export(config: ProjectGoogleSheetsConfig | None) -> bool:
        return bool(config and config.is_enabled and config.spreadsheet_id)

    async def _get_lead_for_export(
        self,
        *,
        lead_id: UUID,
        project_id: UUID,
    ) -> Lead | None:
        result = await self.db.execute(
            select(Lead)
            .options(
                selectinload(Lead.chat)
                .selectinload(Chat.tracking_link)
                .selectinload(TrackingLink.buyer),
                selectinload(Lead.manager),
                selectinload(Lead.status),
            )
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def _get_or_create_worksheet(
        self,
        config: ProjectGoogleSheetsConfig,
    ) -> gspread.Worksheet:
        client = await self._authorize_client()
        spreadsheet = await asyncio.to_thread(client.open_by_key, config.spreadsheet_id)

        try:
            return await asyncio.to_thread(spreadsheet.worksheet, config.sheet_name)
        except WorksheetNotFound:
            worksheet = await asyncio.to_thread(
                spreadsheet.add_worksheet,
                title=config.sheet_name,
                rows=1000,
                cols=len(LEAD_EXPORT_HEADER),
            )
            await asyncio.to_thread(
                worksheet.append_row,
                LEAD_EXPORT_HEADER,
                value_input_option="USER_ENTERED",
            )
            return worksheet

    async def _authorize_client(self) -> gspread.Client:
        credentials = Credentials.from_service_account_info(
            self._service_account_info(),
            scopes=list(GOOGLE_SHEETS_SCOPES),
        )
        return await asyncio.to_thread(gspread.authorize, credentials)

    @staticmethod
    def _service_account_info() -> dict:
        if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
        payload = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        if not isinstance(payload, dict):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must be a JSON object")
        return payload

    async def _build_lead_row(self, lead: Lead) -> list[str | int | float]:
        tracking_link = lead.chat.tracking_link if lead.chat else None
        return [
            self._format_datetime(lead.created_at),
            lead.name or "",
            lead.phone or "",
            self._telegram_value(lead),
            lead.country or "",
            lead.age or "",
            tracking_link.title if tracking_link else "",
            self._buyer_name(lead, tracking_link),
            lead.status.name if lead.status else "",
            float(await self._calculate_cpl(tracking_link.id if tracking_link else None)),
            lead.score_percent if lead.score_percent is not None else "",
        ]

    async def _calculate_cpl(self, tracking_link_id: UUID | None) -> Decimal:
        if tracking_link_id is None:
            return Decimal("0.00")

        spend_result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0)).where(
                TrackingSpend.tracking_link_id == tracking_link_id
            )
        )
        lead_count_result = await self.db.execute(
            select(func.count(distinct(Lead.id)))
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Chat.tracking_link_id == tracking_link_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
            )
        )
        spend = Decimal(str(spend_result.scalar_one() or 0))
        lead_count = int(lead_count_result.scalar_one() or 0)
        if lead_count <= 0:
            return Decimal("0.00")
        return (spend / Decimal(lead_count)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _telegram_value(lead: Lead) -> str:
        if lead.username:
            username = lead.username.strip()
            return username if username.startswith("@") else f"@{username}"
        if lead.chat and lead.chat.external_user_id:
            return lead.chat.external_user_id
        return ""

    @staticmethod
    def _buyer_name(lead: Lead, tracking_link: TrackingLink | None) -> str:
        if tracking_link and tracking_link.buyer:
            return tracking_link.buyer.name
        if tracking_link and tracking_link.buyer_name:
            return tracking_link.buyer_name
        if lead.manager:
            return lead.manager.name
        return ""
