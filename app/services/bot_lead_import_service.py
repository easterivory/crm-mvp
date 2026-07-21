from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import gspread
from fastapi import HTTPException, status
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from requests.exceptions import RequestException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import ChatEventType, LeadStatusCode, RoleName
from app.core.lead_names import compose_lead_name, split_lead_name
from app.models.bot import Bot, BotConfigAuditLog
from app.models.chat import Chat
from app.models.chat_event_log import ChatEventLog
from app.models.lead import Lead, LeadTag
from app.models.lead_import import BotLeadImport
from app.models.lead_status import LeadStatus
from app.models.tag import Tag, random_tag_color
from app.models.user import User
from app.schemas.lead_import import (
    BotLeadImportOut,
    LeadImportExecuteOut,
    LeadImportIssue,
    LeadImportPreviewOut,
)
from app.services.access_control import require_project_access


logger = logging.getLogger(__name__)

IMPORT_WORKSHEET_TITLE = "Перенос лидов"
IMPORT_HEADERS = (
    "Telegram ID",
    "ФИО",
    "Username",
    "Телефон",
    "Страна",
    "Статус",
    "Теги",
    "Сумма для старта",
    "Комментарий менеджера",
)
IMPORT_GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)
MAX_IMPORT_ROWS = 5000
MAX_TAGS_PER_ROW = 50


@dataclass(frozen=True)
class ParsedLeadImportRow:
    row_number: int
    telegram_id: str | None
    full_name: str | None
    username: str | None
    phone: str | None
    country: str | None
    status_value: str | None
    tags: tuple[str, ...]
    expected_start_amount: str | None
    manager_comment: str | None


@dataclass(frozen=True)
class LeadImportAnalysis:
    checksum: str
    rows: tuple[ParsedLeadImportRow, ...]
    rows_to_create: tuple[ParsedLeadImportRow, ...]
    issues: tuple[LeadImportIssue, ...]
    new_tags: tuple[str, ...]
    new_statuses: tuple[str, ...]

    @property
    def errors(self) -> tuple[LeadImportIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "error")

    @property
    def warnings(self) -> tuple[LeadImportIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "warning")

    @property
    def skipped_count(self) -> int:
        return len(self.rows) - len(self.rows_to_create)


class BotLeadImportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_imports(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        actor: User,
    ) -> list[BotLeadImportOut]:
        await self._ensure_access(project_id=project_id, bot_id=bot_id, actor=actor)
        result = await self.db.execute(
            select(BotLeadImport)
            .where(
                BotLeadImport.project_id == project_id,
                BotLeadImport.bot_id == bot_id,
            )
            .order_by(BotLeadImport.created_at.desc(), BotLeadImport.id.desc())
            .limit(20)
        )
        return [BotLeadImportOut.model_validate(item) for item in result.scalars().all()]

    async def create_template(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        actor: User,
    ) -> BotLeadImportOut:
        bot = await self._ensure_access(project_id=project_id, bot_id=bot_id, actor=actor)
        # Do not hold a database transaction while Google Drive/Sheets performs
        # network I/O. The session factory keeps loaded scalar values after commit.
        await self.db.commit()
        client = await self._authorize_google_client()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H-%M UTC")
        title = self._spreadsheet_title(bot.name, timestamp)

        spreadsheet: gspread.Spreadsheet | None = None
        try:
            spreadsheet = await asyncio.to_thread(
                self._create_spreadsheet,
                client,
                title,
            )
            worksheet = spreadsheet.sheet1
            await asyncio.to_thread(worksheet.update_title, IMPORT_WORKSHEET_TITLE)
            await asyncio.to_thread(
                worksheet.append_row,
                list(IMPORT_HEADERS),
                value_input_option="RAW",
            )
            await asyncio.to_thread(
                worksheet.resize,
                rows=MAX_IMPORT_ROWS + 1,
                cols=len(IMPORT_HEADERS),
            )
            await asyncio.to_thread(worksheet.freeze, rows=1)
            await asyncio.to_thread(
                worksheet.format,
                "A1:I1",
                {
                    "backgroundColor": {"red": 0.05, "green": 0.18, "blue": 0.24},
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                    },
                    "horizontalAlignment": "CENTER",
                },
            )
            await asyncio.to_thread(
                worksheet.format,
                f"A2:D{MAX_IMPORT_ROWS + 1}",
                {"numberFormat": {"type": "TEXT"}},
            )
            await asyncio.to_thread(
                spreadsheet.share,
                "",
                perm_type="anyone",
                role="writer",
                notify=False,
                with_link=True,
            )
        except (
            APIError,
            GoogleAuthError,
            PermissionError,
            RequestException,
            ValueError,
        ) as exc:
            if spreadsheet is not None:
                try:
                    await asyncio.to_thread(client.del_spreadsheet, spreadsheet.id)
                except Exception:
                    logger.warning(
                        "Could not remove failed lead import spreadsheet spreadsheet_id=%s",
                        spreadsheet.id,
                        exc_info=True,
                    )
            logger.exception(
                "Google lead import template creation failed project_id=%s bot_id=%s",
                project_id,
                bot_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Google не создал таблицу с публичным доступом на редактирование. "
                    "Проверьте service account, Google Sheets API, Google Drive API и "
                    "политику общего доступа Google Workspace."
                ),
            ) from exc

        if spreadsheet is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google не вернул созданную таблицу",
            )

        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit"
        import_batch = BotLeadImport(
            project_id=project_id,
            bot_id=bot_id,
            created_by_id=actor.id,
            source_system="chatterfy",
            spreadsheet_id=spreadsheet.id,
            spreadsheet_url=spreadsheet_url,
            worksheet_title=IMPORT_WORKSHEET_TITLE,
            status="created",
        )
        try:
            self.db.add(import_batch)
            await self.db.flush()
            await self.db.refresh(import_batch)
            self.db.add(
                BotConfigAuditLog(
                    bot_id=bot_id,
                    user_id=actor.id,
                    action_type="lead_import_template_created",
                    description="Создана Google-таблица для переноса лидов из Chatterfy.",
                )
            )
            await self.db.flush()
            await self.db.commit()
        except Exception:
            try:
                await asyncio.to_thread(client.del_spreadsheet, spreadsheet.id)
            except Exception:
                logger.warning(
                    "Could not remove orphaned lead import spreadsheet spreadsheet_id=%s",
                    spreadsheet.id,
                    exc_info=True,
                )
            raise
        return BotLeadImportOut.model_validate(import_batch)

    async def preview_import(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        import_id: UUID,
        actor: User,
    ) -> LeadImportPreviewOut:
        await self._ensure_access(project_id=project_id, bot_id=bot_id, actor=actor)
        import_batch = await self._get_import(
            project_id=project_id,
            bot_id=bot_id,
            import_id=import_id,
        )
        if import_batch.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Этот импорт уже завершён",
            )

        await self.db.commit()
        values = await self._read_sheet(import_batch)
        analysis = await self._analyze_values(
            values=values,
            project_id=project_id,
            bot_id=bot_id,
        )
        import_batch.preview_checksum = analysis.checksum
        import_batch.total_rows = len(analysis.rows)
        import_batch.error_count = len(analysis.errors)
        import_batch.status = "validated" if not analysis.errors else "created"
        import_batch.preview_summary = {
            "create_count": len(analysis.rows_to_create),
            "skip_count": analysis.skipped_count,
            "warning_count": len(analysis.warnings),
            "new_tags": list(analysis.new_tags),
            "new_statuses": list(analysis.new_statuses),
        }
        await self.db.flush()
        return self._preview_out(import_batch.id, analysis)

    async def execute_import(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        import_id: UUID,
        preview_checksum: str,
        actor: User,
    ) -> LeadImportExecuteOut:
        await self._ensure_access(project_id=project_id, bot_id=bot_id, actor=actor)
        initial_batch = await self._get_import(
            project_id=project_id,
            bot_id=bot_id,
            import_id=import_id,
        )
        if initial_batch.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Этот импорт уже завершён",
            )
        if initial_batch.preview_checksum != preview_checksum:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Повторно проверьте таблицу перед импортом",
            )

        await self.db.commit()
        values = await self._read_sheet(initial_batch)
        analysis = await self._analyze_values(
            values=values,
            project_id=project_id,
            bot_id=bot_id,
        )
        if analysis.checksum != preview_checksum:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Таблица изменилась после проверки. Запустите проверку повторно.",
            )
        if analysis.errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="В Google-таблице есть ошибки валидации",
            )

        result = await self.db.execute(
            select(BotLeadImport)
            .where(
                BotLeadImport.id == import_id,
                BotLeadImport.project_id == project_id,
                BotLeadImport.bot_id == bot_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        import_batch = result.scalar_one_or_none()
        if import_batch is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Импорт не найден")
        if import_batch.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Этот импорт уже завершён",
            )
        if import_batch.preview_checksum != preview_checksum:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Повторно проверьте таблицу перед импортом",
            )

        status_map, created_status_count = await self._ensure_statuses(
            analysis.rows_to_create
        )
        tag_map, created_tag_count = await self._ensure_tags(
            project_id=project_id,
            rows=analysis.rows_to_create,
        )
        now = datetime.now(timezone.utc)
        created_count = 0
        for row in analysis.rows_to_create:
            await self._create_imported_lead(
                row=row,
                import_batch=import_batch,
                project_id=project_id,
                bot_id=bot_id,
                actor_id=actor.id,
                status_map=status_map,
                tag_map=tag_map,
                imported_at=now,
            )
            created_count += 1

        import_batch.status = "completed"
        import_batch.imported_by_id = actor.id
        import_batch.completed_at = now
        import_batch.total_rows = len(analysis.rows)
        import_batch.imported_count = created_count
        import_batch.updated_count = 0
        import_batch.skipped_count = analysis.skipped_count
        import_batch.error_count = 0
        import_batch.error_message = None
        import_batch.preview_summary = {
            **dict(import_batch.preview_summary or {}),
            "created_tag_count": created_tag_count,
            "created_status_count": created_status_count,
        }
        self.db.add(
            BotConfigAuditLog(
                bot_id=bot_id,
                user_id=actor.id,
                action_type="lead_import_completed",
                description=(
                    f"Перенос из Chatterfy завершён: создано {created_count}, "
                    f"пропущено существующих {analysis.skipped_count}."
                ),
            )
        )
        await self.db.flush()
        await self.db.refresh(import_batch)
        return LeadImportExecuteOut(
            import_batch=BotLeadImportOut.model_validate(import_batch),
            created_count=created_count,
            skipped_count=analysis.skipped_count,
            created_tag_count=created_tag_count,
            created_status_count=created_status_count,
        )

    async def _ensure_access(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        actor: User,
    ) -> Bot:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Перенос лидов доступен только администратору",
            )
        require_project_access(actor, project_id)
        result = await self.db.execute(
            select(Bot).where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
        )
        bot = result.scalar_one_or_none()
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Бот не найден")
        return bot

    async def _get_import(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        import_id: UUID,
    ) -> BotLeadImport:
        result = await self.db.execute(
            select(BotLeadImport).where(
                BotLeadImport.id == import_id,
                BotLeadImport.project_id == project_id,
                BotLeadImport.bot_id == bot_id,
            )
        )
        import_batch = result.scalar_one_or_none()
        if import_batch is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Импорт не найден")
        return import_batch

    async def _read_sheet(self, import_batch: BotLeadImport) -> list[list[str]]:
        client = await self._authorize_google_client()
        try:
            spreadsheet = await asyncio.to_thread(
                client.open_by_key,
                import_batch.spreadsheet_id,
            )
            worksheet = await asyncio.to_thread(
                spreadsheet.worksheet,
                import_batch.worksheet_title,
            )
            values = await asyncio.to_thread(worksheet.get_all_values)
        except SpreadsheetNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Таблица недоступна сервисному аккаунту CRM",
            ) from exc
        except WorksheetNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Лист «{import_batch.worksheet_title}» удалён или переименован"
                ),
            ) from exc
        except (APIError, GoogleAuthError, RequestException) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Не удалось прочитать таблицу через Google Sheets API: {exc}",
            ) from exc
        return [[str(cell) for cell in row] for row in values]

    async def _analyze_values(
        self,
        *,
        values: list[list[str]],
        project_id: UUID,
        bot_id: UUID,
    ) -> LeadImportAnalysis:
        checksum = self._sheet_checksum(values)
        issues: list[LeadImportIssue] = []
        if not values or tuple(self._pad_row(values[0])) != IMPORT_HEADERS:
            issues.append(
                LeadImportIssue(
                    row=2,
                    field="Заголовки",
                    level="error",
                    message="Не изменяйте названия и порядок колонок созданного шаблона.",
                )
            )
            return LeadImportAnalysis(
                checksum=checksum,
                rows=(),
                rows_to_create=(),
                issues=tuple(issues),
                new_tags=(),
                new_statuses=(),
            )

        raw_rows = [row for row in values[1:] if any(str(cell).strip() for cell in row)]
        if len(raw_rows) > MAX_IMPORT_ROWS:
            issues.append(
                LeadImportIssue(
                    row=2,
                    field="Таблица",
                    level="error",
                    message=f"За один импорт допускается не более {MAX_IMPORT_ROWS} строк.",
                )
            )
        parsed_rows: list[ParsedLeadImportRow] = []
        seen_telegram_ids: dict[str, int] = {}
        seen_usernames: dict[str, int] = {}
        for index, raw_row in enumerate(raw_rows[:MAX_IMPORT_ROWS], start=2):
            row, row_issues = self._parse_row(index, raw_row)
            issues.extend(row_issues)
            if row is None:
                continue
            if row.telegram_id:
                previous = seen_telegram_ids.get(row.telegram_id)
                if previous is not None:
                    issues.append(
                        LeadImportIssue(
                            row=index,
                            field="Telegram ID",
                            level="error",
                            message=f"Telegram ID уже указан в строке {previous}.",
                        )
                    )
                else:
                    seen_telegram_ids[row.telegram_id] = index
            if row.username:
                previous = seen_usernames.get(row.username)
                if previous is not None:
                    issues.append(
                        LeadImportIssue(
                            row=index,
                            field="Username",
                            level="error",
                            message=f"Username уже указан в строке {previous}.",
                        )
                    )
                else:
                    seen_usernames[row.username] = index
            parsed_rows.append(row)

        existing_telegram_ids, existing_usernames = await self._existing_identities(
            project_id=project_id,
            bot_id=bot_id,
        )
        rows_to_create: list[ParsedLeadImportRow] = []
        for row in parsed_rows:
            existing_by_id = bool(
                row.telegram_id and row.telegram_id in existing_telegram_ids
            )
            existing_by_username = bool(
                row.username and row.username in existing_usernames
            )
            if existing_by_id or existing_by_username:
                matched_by = "Telegram ID" if existing_by_id else "username"
                issues.append(
                    LeadImportIssue(
                        row=row.row_number,
                        field=matched_by,
                        level="warning",
                        message=(
                            "Чат уже существует в CRM и будет пропущен, чтобы не "
                            "перезаписать актуальные данные."
                        ),
                    )
                )
                continue
            rows_to_create.append(row)

        existing_statuses = await self._existing_status_values()
        existing_tags = await self._existing_tag_values(project_id)
        new_statuses = self._ordered_unique(
            row.status_value
            for row in rows_to_create
            if row.status_value
            and self._normalize_lookup(row.status_value) not in existing_statuses
        )
        new_tags = self._ordered_unique(
            tag
            for row in rows_to_create
            for tag in row.tags
            if self._normalize_lookup(tag) not in existing_tags
        )
        if not parsed_rows and not issues:
            issues.append(
                LeadImportIssue(
                    row=2,
                    field="Таблица",
                    level="error",
                    message="Добавьте хотя бы одного лида перед проверкой.",
                )
            )
        return LeadImportAnalysis(
            checksum=checksum,
            rows=tuple(parsed_rows),
            rows_to_create=tuple(rows_to_create),
            issues=tuple(issues),
            new_tags=tuple(new_tags),
            new_statuses=tuple(new_statuses),
        )

    def _parse_row(
        self,
        row_number: int,
        raw_row: list[str],
    ) -> tuple[ParsedLeadImportRow | None, list[LeadImportIssue]]:
        values = self._pad_row(raw_row)
        telegram_raw, full_name, username_raw, phone, country, status_value, _, amount, comment = (
            self._clean_text(value) for value in values
        )
        tags_raw = str(values[6] or "").strip() or None
        issues: list[LeadImportIssue] = []
        telegram_id = self._normalize_telegram_id(telegram_raw)
        if telegram_raw and telegram_id is None:
            issues.append(
                LeadImportIssue(
                    row=row_number,
                    field="Telegram ID",
                    level="error",
                    message="Укажите положительный числовой Telegram ID без букв.",
                )
            )
        username = self._normalize_username(username_raw)
        if username_raw and username is None:
            issues.append(
                LeadImportIssue(
                    row=row_number,
                    field="Username",
                    level="error",
                    message="Username содержит недопустимые символы.",
                )
            )
        if telegram_id is None and username is None:
            issues.append(
                LeadImportIssue(
                    row=row_number,
                    field="Telegram ID / Username",
                    level="error",
                    message="Заполните Telegram ID или username.",
                )
            )
        if telegram_id is None and username is not None:
            issues.append(
                LeadImportIssue(
                    row=row_number,
                    field="Telegram ID",
                    level="warning",
                    message=(
                        "Связывание будет выполнено по username при первом сообщении. "
                        "Telegram ID надёжнее, потому что username может измениться."
                    ),
                )
            )

        self._validate_length(issues, row_number, "ФИО", full_name, 255)
        self._validate_length(issues, row_number, "Телефон", phone, 50)
        self._validate_length(issues, row_number, "Страна", country, 100)
        self._validate_length(issues, row_number, "Статус", status_value, 100)
        self._validate_length(issues, row_number, "Сумма для старта", amount, 100)
        self._validate_length(issues, row_number, "Комментарий менеджера", comment, 5000)

        tags = self._parse_tags(tags_raw)
        if len(tags) > MAX_TAGS_PER_ROW:
            issues.append(
                LeadImportIssue(
                    row=row_number,
                    field="Теги",
                    level="error",
                    message=f"Допускается не более {MAX_TAGS_PER_ROW} тегов на одного лида.",
                )
            )
        for tag in tags:
            self._validate_length(issues, row_number, "Теги", tag, 100)

        if any(issue.level == "error" for issue in issues):
            return None, issues
        return (
            ParsedLeadImportRow(
                row_number=row_number,
                telegram_id=telegram_id,
                full_name=full_name,
                username=username,
                phone=phone,
                country=country,
                status_value=status_value,
                tags=tags,
                expected_start_amount=amount,
                manager_comment=comment,
            ),
            issues,
        )

    async def _existing_identities(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
    ) -> tuple[set[str], set[str]]:
        result = await self.db.execute(
            select(Chat.external_chat_id, Chat.import_username_key, Lead.username)
            .outerjoin(
                Lead,
                (Lead.chat_id == Chat.id) & Lead.is_deleted.is_(False),
            )
            .where(
                Chat.project_id == project_id,
                Chat.bot_id == bot_id,
                Chat.is_deleted.is_(False),
            )
        )
        telegram_ids: set[str] = set()
        usernames: set[str] = set()
        for external_chat_id, import_username_key, lead_username in result.all():
            if str(external_chat_id).isdigit():
                telegram_ids.add(str(external_chat_id))
            for value in (import_username_key, lead_username):
                normalized = self._normalize_username(value)
                if normalized:
                    usernames.add(normalized)
        return telegram_ids, usernames

    async def _existing_status_values(self) -> dict[str, LeadStatus]:
        result = await self.db.execute(select(LeadStatus))
        values: dict[str, LeadStatus] = {}
        for lead_status in result.scalars().all():
            values[self._normalize_lookup(lead_status.code)] = lead_status
            values[self._normalize_lookup(lead_status.name)] = lead_status
        return values

    async def _existing_tag_values(self, project_id: UUID) -> dict[str, Tag]:
        result = await self.db.execute(select(Tag).where(Tag.project_id == project_id))
        return {
            self._normalize_lookup(tag.name): tag
            for tag in result.scalars().all()
        }

    async def _ensure_statuses(
        self,
        rows: tuple[ParsedLeadImportRow, ...],
    ) -> tuple[dict[str, LeadStatus], int]:
        status_map = await self._existing_status_values()
        default_status = status_map.get(self._normalize_lookup(LeadStatusCode.NEW))
        created_count = 0
        if default_status is None:
            default_status = LeadStatus(
                code=LeadStatusCode.NEW,
                name="New",
                sort_order=0,
                is_final=False,
            )
            self.db.add(default_status)
            await self.db.flush()
            status_map[self._normalize_lookup(LeadStatusCode.NEW)] = default_status
            status_map[self._normalize_lookup(default_status.name)] = default_status
            created_count += 1

        next_sort_result = await self.db.execute(
            select(func.coalesce(func.max(LeadStatus.sort_order), 0))
        )
        next_sort_order = int(next_sort_result.scalar_one()) + 1
        for status_name in self._ordered_unique(
            row.status_value for row in rows if row.status_value
        ):
            key = self._normalize_lookup(status_name)
            if key in status_map:
                continue
            lead_status = LeadStatus(
                code=self._imported_status_code(status_name),
                name=status_name,
                sort_order=next_sort_order,
                is_final=False,
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(lead_status)
                    await self.db.flush()
            except IntegrityError:
                status_map = await self._existing_status_values()
                existing = status_map.get(key)
                if existing is None:
                    raise
                continue
            status_map[key] = lead_status
            status_map[self._normalize_lookup(lead_status.code)] = lead_status
            next_sort_order += 1
            created_count += 1
        status_map[""] = default_status
        return status_map, created_count

    async def _ensure_tags(
        self,
        *,
        project_id: UUID,
        rows: tuple[ParsedLeadImportRow, ...],
    ) -> tuple[dict[str, Tag], int]:
        tag_map = await self._existing_tag_values(project_id)
        created_count = 0
        for tag_name in self._ordered_unique(tag for row in rows for tag in row.tags):
            key = self._normalize_lookup(tag_name)
            if key in tag_map:
                continue
            tag = Tag(project_id=project_id, name=tag_name, color=random_tag_color())
            try:
                async with self.db.begin_nested():
                    self.db.add(tag)
                    await self.db.flush()
            except IntegrityError:
                tag_map = await self._existing_tag_values(project_id)
                existing = tag_map.get(key)
                if existing is None:
                    raise
                continue
            tag_map[key] = tag
            created_count += 1
        return tag_map, created_count

    async def _create_imported_lead(
        self,
        *,
        row: ParsedLeadImportRow,
        import_batch: BotLeadImport,
        project_id: UUID,
        bot_id: UUID,
        actor_id: UUID,
        status_map: dict[str, LeadStatus],
        tag_map: dict[str, Tag],
        imported_at: datetime,
    ) -> None:
        username_pending = row.username is not None
        external_identity = row.telegram_id or f"import:{import_batch.id}:{row.row_number}"
        chat = Chat(
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_identity,
            external_user_id=external_identity,
            contact_name=row.full_name or (f"@{row.username}" if row.username else None),
            last_message_at=imported_at,
            is_read=False,
            is_imported=True,
            lead_import_id=import_batch.id,
            imported_at=imported_at,
            import_username_key=row.username,
            import_identity_pending=username_pending,
        )
        self.db.add(chat)
        await self.db.flush()

        first_name, last_name = split_lead_name(row.full_name, username=row.username)
        custom_fields: dict[str, Any] = {}
        if first_name:
            custom_fields["first_name"] = first_name
        if last_name:
            custom_fields["last_name"] = last_name
        if row.full_name:
            custom_fields["__crm_name_override"] = True
        if row.expected_start_amount:
            custom_fields["expected_start_amount"] = row.expected_start_amount

        status_key = self._normalize_lookup(row.status_value or "")
        lead_status = status_map.get(status_key) or status_map[""]
        lead = Lead(
            project_id=project_id,
            chat_id=chat.id,
            status_id=lead_status.id,
            name=compose_lead_name(first_name, last_name) or row.full_name,
            username=row.username,
            phone=row.phone,
            country=row.country,
            manager_comment=row.manager_comment,
            custom_fields=custom_fields,
        )
        self.db.add(lead)
        await self.db.flush()
        for tag_name in row.tags:
            tag = tag_map[self._normalize_lookup(tag_name)]
            self.db.add(LeadTag(lead_id=lead.id, tag_id=tag.id))

        self.db.add(
            ChatEventLog(
                chat_id=chat.id,
                user_id=actor_id,
                event_type=ChatEventType.NOTE_ADDED,
                new_value=self._import_note(row, lead_status.name),
            )
        )
        await self.db.flush()

    @staticmethod
    def _import_note(row: ParsedLeadImportRow, status_name: str) -> str:
        parts = ["Лид импортирован из Chatterfy"]
        for label, value in (
            ("ФИО", row.full_name),
            ("Telegram ID", row.telegram_id),
            ("Username", f"@{row.username}" if row.username else None),
            ("Телефон", row.phone),
            ("Страна", row.country),
            ("Статус", status_name),
            ("Теги", ", ".join(row.tags) if row.tags else None),
            ("Сумма для старта", row.expected_start_amount),
            ("Комментарий менеджера", row.manager_comment),
        ):
            if value:
                parts.append(f"{label}: {value}")
        return "; ".join(parts)

    async def _authorize_google_client(self) -> gspread.Client:
        try:
            credentials = Credentials.from_service_account_info(
                self._service_account_info(),
                scopes=list(IMPORT_GOOGLE_SCOPES),
            )
            return await asyncio.to_thread(gspread.authorize, credentials)
        except (json.JSONDecodeError, ValueError, GoogleAuthError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="GOOGLE_SERVICE_ACCOUNT_JSON не настроен или содержит ошибку",
            ) from exc

    @staticmethod
    def _service_account_info() -> dict[str, Any]:
        if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
        payload = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        if not isinstance(payload, dict):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must be a JSON object")
        private_key = payload.get("private_key")
        if isinstance(private_key, str):
            payload["private_key"] = private_key.replace("\\n", "\n")
        required = {"client_email", "private_key", "token_uri"}
        if any(not payload.get(key) for key in required):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is incomplete")
        return payload

    @staticmethod
    def _create_spreadsheet(client: gspread.Client, title: str) -> gspread.Spreadsheet:
        folder_id = (settings.GOOGLE_LEAD_IMPORT_FOLDER_ID or "").strip()
        if folder_id:
            return client.create(title, folder_id=folder_id)
        return client.create(title)

    @staticmethod
    def _preview_out(import_id: UUID, analysis: LeadImportAnalysis) -> LeadImportPreviewOut:
        return LeadImportPreviewOut(
            import_id=import_id,
            checksum=analysis.checksum,
            can_import=bool(analysis.rows_to_create) and not analysis.errors,
            total_rows=len(analysis.rows),
            create_count=len(analysis.rows_to_create),
            skip_count=analysis.skipped_count,
            error_count=len(analysis.errors),
            warning_count=len(analysis.warnings),
            new_tags=list(analysis.new_tags),
            new_statuses=list(analysis.new_statuses),
            issues=list(analysis.issues),
        )

    @staticmethod
    def _sheet_checksum(values: list[list[str]]) -> str:
        canonical = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _spreadsheet_title(bot_name: str, timestamp: str) -> str:
        normalized = " ".join(str(bot_name or "Telegram bot").split())[:80]
        return f"CRM перенос лидов - {normalized} - {timestamp}"

    @staticmethod
    def _pad_row(row: list[str]) -> list[str]:
        return [str(value) for value in row[: len(IMPORT_HEADERS)]] + [
            ""
        ] * max(0, len(IMPORT_HEADERS) - len(row))

    @staticmethod
    def _clean_text(value: Any) -> str | None:
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @staticmethod
    def _normalize_telegram_id(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lstrip("'")
        if re.fullmatch(r"\d+(?:\.0+)?", normalized):
            parsed_digits = normalized.split(".", 1)[0].lstrip("0")
            return parsed_digits or None
        try:
            parsed = Decimal(normalized)
        except InvalidOperation:
            return None
        if not parsed.is_finite() or parsed <= 0 or parsed != parsed.to_integral_value():
            return None
        return str(int(parsed))

    @staticmethod
    def _normalize_username(value: Any) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        normalized = re.sub(
            r"^(?:https?://)?(?:t\.me|telegram\.me)/",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = normalized.split("?", 1)[0].strip().removeprefix("@").lower()
        if not re.fullmatch(r"[a-z0-9_]{5,32}", normalized):
            return None
        return normalized

    @staticmethod
    def _parse_tags(value: str | None) -> tuple[str, ...]:
        if not value:
            return ()
        values: list[str] = []
        seen: set[str] = set()
        for item in re.split(r"[,;|\n]+", value):
            normalized = " ".join(item.strip().split())
            key = normalized.casefold()
            if normalized and key not in seen:
                values.append(normalized)
                seen.add(key)
        return tuple(values)

    @staticmethod
    def _validate_length(
        issues: list[LeadImportIssue],
        row_number: int,
        field: str,
        value: str | None,
        max_length: int,
    ) -> None:
        if value is not None and len(value) > max_length:
            issues.append(
                LeadImportIssue(
                    row=row_number,
                    field=field,
                    level="error",
                    message=f"Максимальная длина поля: {max_length} символов.",
                )
            )

    @staticmethod
    def _normalize_lookup(value: str) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @classmethod
    def _ordered_unique(cls, values: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not value:
                continue
            normalized = cls._normalize_lookup(value)
            if normalized not in seen:
                result.append(value)
                seen.add(normalized)
        return result

    @classmethod
    def _imported_status_code(cls, name: str) -> str:
        digest = hashlib.sha256(cls._normalize_lookup(name).encode("utf-8")).hexdigest()[:16]
        return f"imported_{digest}"
