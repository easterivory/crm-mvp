from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

import gspread
from google.auth.exceptions import GoogleAuthError
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
from app.schemas.google_sheets import DEFAULT_GOOGLE_SHEETS_EXPORT_FIELDS

logger = logging.getLogger(__name__)

GOOGLE_SHEETS_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
EXPORT_FIELD_LABELS = {
    "created_at": "Дата создания",
    "name": "Имя",
    "phone": "Телефон",
    "telegram": "Telegram",
    "country": "Страна",
    "age": "Возраст",
    "tracking_link": "Ссылка",
    "buyer": "Баер",
    "status": "Статус",
    "cpl": "CPL ($)",
    "score": "Уверенность (%)",
    "manager": "Менеджер",
    "bot": "Бот",
    "chat_id": "CRM Chat ID",
    "telegram_id": "Telegram ID",
}


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
        if config.bot_ids and (
            lead.chat is None or str(lead.chat.bot_id) not in set(config.bot_ids)
        ):
            logger.info(
                "Google Sheets export skipped by bot filter lead_id=%s bot_id=%s",
                lead_id,
                lead.chat.bot_id if lead.chat else None,
            )
            return

        try:
            worksheet = await self._get_or_create_worksheet(config)
            await asyncio.to_thread(
                worksheet.append_row,
                await self._build_lead_row(lead, config),
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
        except (json.JSONDecodeError, ValueError, GoogleAuthError, PermissionError) as exc:
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
            return True, (
                f"Подключение работает. Лист «{worksheet.title}» доступен для записи "
                f"аккаунту {settings.GOOGLE_SERVICE_ACCOUNT_EMAIL}."
            )
        except SpreadsheetNotFound:
            return False, (
                "Таблица не найдена или не расшарена сервисному аккаунту "
                f"{settings.GOOGLE_SERVICE_ACCOUNT_EMAIL or 'не определён'}. "
                "Проверьте Spreadsheet ID и выдайте этому email роль Редактор в самой таблице."
            )
        except APIError as exc:
            logger.warning(
                "Google Sheets test connection failed project_id=%s spreadsheet_id=%s "
                "service_account_email=%s error=%s",
                project_id,
                config.spreadsheet_id,
                settings.GOOGLE_SERVICE_ACCOUNT_EMAIL,
                exc,
            )
            return False, self._api_error_message(exc)
        except (json.JSONDecodeError, ValueError, GoogleAuthError, PermissionError) as exc:
            logger.warning(
                "Google Sheets test connection skipped due to invalid service account config "
                "project_id=%s error=%s",
                project_id,
                exc,
            )
            return False, self._credentials_error_message(exc)

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
                selectinload(Lead.chat).selectinload(Chat.bot),
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
            worksheet = await asyncio.to_thread(spreadsheet.worksheet, config.sheet_name)
        except WorksheetNotFound:
            worksheet = await asyncio.to_thread(
                spreadsheet.add_worksheet,
                title=config.sheet_name,
                rows=1000,
                cols=max(len(self._export_header(config)), 1),
            )
        await self._ensure_header(worksheet, config)
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
        private_key = payload.get("private_key")
        if isinstance(private_key, str):
            payload["private_key"] = private_key.replace("\\n", "\n")
        required = {"client_email", "private_key", "token_uri"}
        missing = sorted(key for key in required if not payload.get(key))
        if missing:
            raise ValueError(
                f"GOOGLE_SERVICE_ACCOUNT_JSON is missing fields: {', '.join(missing)}"
            )
        return payload

    async def _build_lead_row(
        self,
        lead: Lead,
        config: ProjectGoogleSheetsConfig,
    ) -> list[str | int | float]:
        tracking_link = lead.chat.tracking_link if lead.chat else None
        values: dict[str, str | int | float] = {
            "created_at": self._format_datetime(lead.created_at),
            "name": lead.name or "",
            "phone": lead.phone or "",
            "telegram": self._telegram_value(lead),
            "country": lead.country or "",
            "age": lead.age or "",
            "tracking_link": tracking_link.title if tracking_link else "",
            "buyer": self._buyer_name(lead, tracking_link),
            "status": lead.status.name if lead.status else "",
            "cpl": float(await self._calculate_cpl(tracking_link.id if tracking_link else None)),
            "score": lead.score_percent if lead.score_percent is not None else "",
            "manager": lead.manager.name if lead.manager else "",
            "bot": lead.chat.bot.name if lead.chat and lead.chat.bot else "",
            "chat_id": str(lead.chat_id),
            "telegram_id": lead.chat.external_user_id if lead.chat else "",
        }
        export_fields = config.export_fields or DEFAULT_GOOGLE_SHEETS_EXPORT_FIELDS
        row = [values.get(field, "") for field in export_fields]
        custom_fields = dict(lead.custom_fields or {})
        row.extend(self._sheet_scalar(custom_fields.get(key)) for key in config.custom_field_keys or [])
        return row

    async def _ensure_header(
        self,
        worksheet: gspread.Worksheet,
        config: ProjectGoogleSheetsConfig,
    ) -> None:
        expected = self._export_header(config)
        existing = await asyncio.to_thread(worksheet.row_values, 1)
        if not existing:
            await asyncio.to_thread(
                worksheet.append_row,
                expected,
                value_input_option="USER_ENTERED",
            )
            return
        if existing[: len(expected)] != expected or len(existing) != len(expected):
            raise ValueError(
                "Заголовки листа не совпадают с выбранными полями экспорта. "
                "Выберите пустой лист или верните прежний набор полей."
            )

    @staticmethod
    def _export_header(config: ProjectGoogleSheetsConfig) -> list[str]:
        fields = config.export_fields or DEFAULT_GOOGLE_SHEETS_EXPORT_FIELDS
        return [EXPORT_FIELD_LABELS[field] for field in fields] + [
            f"Доп. поле: {key}" for key in config.custom_field_keys or []
        ]

    @staticmethod
    def _sheet_scalar(value: object) -> str | int | float:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "Да" if value else "Нет"
        if isinstance(value, (str, int, float)):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _credentials_error_message(exc: Exception) -> str:
        return (
            f"Не удалось прочитать service-account credentials ({exc.__class__.__name__}: {exc}). "
            "Передайте полный JSON одной строкой; private_key должен содержать корректные переносы \\n."
        )

    @staticmethod
    def _api_error_message(exc: APIError) -> str:
        return (
            f"Google Sheets API отклонил запрос: {exc}. Проверьте, что Sheets API включён "
            "в том же Google Cloud project и таблица расшарена сервисному аккаунту как Редактор."
        )

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
