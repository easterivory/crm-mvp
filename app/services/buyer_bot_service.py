"""Buyer Telegram bot service.

The buyer bot is a private Telegram workspace for media buyers who do not use
the web CRM. It binds a Telegram chat to an existing CRM user through a one-time
invite token, then lets the buyer create tracking links, add spend, and inspect
their own traffic analytics.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import string
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis
from sqlalchemy import distinct, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import TrackingSpendSource
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import FunnelStep, FunnelStepLog
from app.models.lead import Lead
from app.models.tracking import TrackingEvent, TrackingLink, TrackingSpend
from app.models.user import User
from app.schemas.telegram import TelegramCallbackQuery, TelegramMessage, TelegramUpdate

logger = logging.getLogger(__name__)

MAIN_MENU_MARKUP: dict[str, Any] = {
    "keyboard": [
        [{"text": "Мои ссылки"}, {"text": "Создать ссылку"}],
        [{"text": "Ввести расход"}, {"text": "Статистика"}],
        [{"text": "Воронка отвалов"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

STATE_CREATE_LINK_NAME = "create_link_name"
STATE_SPEND_DATE = "spend_date"
STATE_SPEND_AMOUNT = "spend_amount"
MAX_LINKS_IN_KEYBOARD = 30
REF_CODE_LENGTH = 6


@dataclass(frozen=True, slots=True)
class BuyerPeriodStats:
    label: str
    spend: Decimal
    leads: int
    clicks: int

    @property
    def cpl(self) -> Decimal:
        if self.leads <= 0:
            return Decimal("0.00")
        return money(self.spend / Decimal(self.leads))

    @property
    def lead_conversion_percent(self) -> Decimal:
        if self.clicks <= 0:
            return Decimal("0.00")
        return percent(Decimal(self.leads) / Decimal(self.clicks) * Decimal("100"))


@dataclass(frozen=True, slots=True)
class BuyerFunnelStepStats:
    position: int
    title: str
    count: int
    reached_percent: Decimal
    dropoff_percent: Decimal


class BuyerBotStateStore:
    """Redis-backed FSM state for buyer chat flows."""

    def __init__(self, redis_url: str | None = None, ttl_seconds: int | None = None) -> None:
        self.redis = Redis.from_url(
            redis_url or settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        self.ttl_seconds = ttl_seconds or settings.BUYER_BOT_FSM_TTL_SECONDS

    async def get(self, telegram_chat_id: int) -> dict[str, Any] | None:
        raw = await self.redis.get(self._key(telegram_chat_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await self.clear(telegram_chat_id)
            return None
        return payload if isinstance(payload, dict) else None

    async def set(self, telegram_chat_id: int, payload: dict[str, Any]) -> None:
        await self.redis.set(
            self._key(telegram_chat_id),
            json.dumps(payload, ensure_ascii=False),
            ex=self.ttl_seconds,
        )

    async def clear(self, telegram_chat_id: int) -> None:
        await self.redis.delete(self._key(telegram_chat_id))

    async def close(self) -> None:
        await self.redis.aclose()

    @staticmethod
    def _key(telegram_chat_id: int) -> str:
        return f"buyer_bot:fsm:{telegram_chat_id}"


class BuyerTelegramClient:
    """Small async Telegram Bot API client for the buyer bot token."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds or settings.BUYER_BOT_POLL_TIMEOUT_SECONDS,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = await self._post("getUpdates", payload)
        result = response.get("result")
        return result if isinstance(result, list) else []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self._post("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str) -> None:
        try:
            await self._post("answerCallbackQuery", {"callback_query_id": callback_query_id})
        except RuntimeError:
            logger.debug("Buyer bot answerCallbackQuery failed", exc_info=True)

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=35.0) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Telegram {method} returned non-JSON response") from exc

        if response.status_code >= 400 or data.get("ok") is not True:
            description = data.get("description") or response.text[:500]
            raise RuntimeError(f"Telegram {method} failed: {description}")
        return data


class BuyerBotService:
    def __init__(
        self,
        db: AsyncSession,
        telegram: BuyerTelegramClient,
        state_store: BuyerBotStateStore,
    ) -> None:
        self.db = db
        self.telegram = telegram
        self.state_store = state_store

    async def handle_update(self, update: TelegramUpdate) -> None:
        if update.message is not None:
            await self._handle_message(update.message)
            return

        if update.callback_query is not None:
            await self._handle_callback(update.callback_query)

    async def _handle_message(self, message: TelegramMessage) -> None:
        chat_id = message.chat.id
        text = (message.text or "").strip()
        if not text:
            await self.telegram.send_message(chat_id, "Пришли текстовую команду.", reply_markup=MAIN_MENU_MARKUP)
            return

        command, argument = self._split_command(text)
        if self._is_start_command(command):
            if argument:
                await self._activate(chat_id, argument)
                return

            buyer = await self._get_buyer_by_telegram_id(chat_id)
            if buyer is None:
                await self.telegram.send_message(
                    chat_id,
                    "Аккаунт еще не привязан. Открой инвайт-ссылку от администратора.",
                )
                return

            await self._send_menu(chat_id, buyer)
            return

        buyer = await self._require_buyer(chat_id)
        if buyer is None:
            return

        if command in {"/cancel", "Отмена"}:
            await self.state_store.clear(chat_id)
            await self.telegram.send_message(chat_id, "Действие отменено.", reply_markup=MAIN_MENU_MARKUP)
            return

        if command in {"/create_link", "Создать ссылку"}:
            await self._start_create_link(chat_id)
            return
        if command in {"/links", "Мои ссылки"}:
            await self._send_links(chat_id, buyer)
            return
        if command in {"/spend", "Ввести расход"}:
            await self._start_spend(chat_id, buyer)
            return
        if command in {"/stats", "Статистика"}:
            await self._send_stats(chat_id, buyer)
            return
        if command in {"/funnel", "Воронка отвалов"}:
            await self._send_funnel(chat_id, buyer)
            return

        state = await self.state_store.get(chat_id)
        if state and state.get("state") == STATE_CREATE_LINK_NAME:
            await self._finish_create_link(chat_id, buyer, text)
            return
        if state and state.get("state") == STATE_SPEND_AMOUNT:
            await self._finish_spend(chat_id, buyer, state, text)
            return

        await self.telegram.send_message(
            chat_id,
            "Выбери действие в меню или используй команды /create_link, /spend, /stats, /funnel.",
            reply_markup=MAIN_MENU_MARKUP,
        )

    async def _handle_callback(self, callback_query: TelegramCallbackQuery) -> None:
        if not callback_query.data:
            return

        await self.telegram.answer_callback_query(callback_query.id)
        chat_id = self._callback_chat_id(callback_query)
        if chat_id is None:
            return

        buyer = await self._require_buyer(chat_id)
        if buyer is None:
            return

        data = callback_query.data
        if data.startswith("spend_link:"):
            await self._select_spend_link(chat_id, buyer, data.removeprefix("spend_link:"))
            return

        if data.startswith("spend_date:"):
            await self._select_spend_date(chat_id, buyer, data.removeprefix("spend_date:"))
            return

    async def _activate(self, chat_id: int, raw_token: str) -> None:
        token = self._normalize_activation_token(raw_token)
        if token is None:
            await self.telegram.send_message(
                chat_id,
                "Инвайт-токен некорректен. Попроси администратора выпустить новую ссылку.",
            )
            return

        user_result = await self.db.execute(
            select(User).where(
                User.buyer_invite_token == token,
                User.is_deleted.is_(False),
            )
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            await self.telegram.send_message(
                chat_id,
                "Инвайт не найден или уже использован. Попроси администратора выпустить новую ссылку.",
            )
            return

        existing_result = await self.db.execute(
            select(User).where(
                User.buyer_telegram_id == chat_id,
                User.id != user.id,
                User.is_deleted.is_(False),
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            await self.telegram.send_message(
                chat_id,
                "Этот Telegram уже привязан к другому пользователю CRM. Обратись к администратору.",
            )
            return

        user.buyer_telegram_id = chat_id
        user.buyer_invite_token = None
        await self.db.commit()
        await self.state_store.clear(chat_id)

        await self.telegram.send_message(
            chat_id,
            f"Привет, {user.name}! Аккаунт привязан.\n\n"
            "Тебе доступны: Мои ссылки, Ввести расход, Статистика, Воронка отвалов.",
            reply_markup=MAIN_MENU_MARKUP,
        )

    async def _send_menu(self, chat_id: int, buyer: User) -> None:
        await self.telegram.send_message(
            chat_id,
            f"{buyer.name}, выбери действие:",
            reply_markup=MAIN_MENU_MARKUP,
        )

    async def _start_create_link(self, chat_id: int) -> None:
        await self.state_store.set(chat_id, {"state": STATE_CREATE_LINK_NAME})
        await self.telegram.send_message(
            chat_id,
            "Пришли название ссылки, например: tiktok_camp_3.\n\n"
            "Команда /cancel отменит действие.",
        )

    async def _finish_create_link(self, chat_id: int, buyer: User, raw_name: str) -> None:
        title = self._normalize_link_title(raw_name)
        if title is None:
            await self.telegram.send_message(
                chat_id,
                "Название должно содержать хотя бы 2 символа. Попробуй еще раз или отправь /cancel.",
            )
            return
        if buyer.project_id is None:
            await self.telegram.send_message(
                chat_id,
                "У твоего пользователя не указан проект. Администратор должен привязать баера к проекту.",
            )
            await self.state_store.clear(chat_id)
            return

        bot = await self._resolve_client_bot(buyer.project_id)
        if bot is None or not bot.bot_username:
            await self.telegram.send_message(
                chat_id,
                "В проекте не найден клиентский Telegram-бот с username. Проверь настройки бота в CRM.",
            )
            await self.state_store.clear(chat_id)
            return

        invite_link: str | None = None
        for _ in range(3):
            code = await self._generate_unique_ref_code()
            invite_link = self._build_client_start_link(bot.bot_username, code)
            self.db.add(
                TrackingLink(
                    project_id=buyer.project_id,
                    bot_id=bot.id,
                    name=title,
                    title=title,
                    ref_code=code,
                    code=code,
                    buyer_id=buyer.id,
                    buyer_name=buyer.name,
                    invite_link=invite_link,
                    created_by_user_id=buyer.id,
                )
            )
            try:
                await self.db.commit()
                break
            except IntegrityError:
                await self.db.rollback()
        else:
            await self.telegram.send_message(
                chat_id,
                "Не удалось сгенерировать уникальный код ссылки. Попробуй еще раз.",
                reply_markup=MAIN_MENU_MARKUP,
            )
            await self.state_store.clear(chat_id)
            return

        await self.state_store.clear(chat_id)
        await self.telegram.send_message(
            chat_id,
            f"Ссылка создана:\n{title}\n\n{invite_link}",
            reply_markup=MAIN_MENU_MARKUP,
        )

    async def _send_links(self, chat_id: int, buyer: User) -> None:
        links = await self._list_buyer_links(buyer.id, limit=20)
        if not links:
            await self.telegram.send_message(
                chat_id,
                "У тебя пока нет ссылок. Нажми «Создать ссылку» или отправь /create_link.",
                reply_markup=MAIN_MENU_MARKUP,
            )
            return

        lines = ["Твои ссылки:"]
        for index, link in enumerate(links, start=1):
            invite_link = link.invite_link or self._build_client_start_link(
                link.bot.bot_username if link.bot else None,
                link.code or link.ref_code,
            )
            lines.append(f"{index}. {link.title or link.name}\n{invite_link}")

        await self.telegram.send_message(chat_id, "\n\n".join(lines), reply_markup=MAIN_MENU_MARKUP)

    async def _start_spend(self, chat_id: int, buyer: User) -> None:
        links = await self._list_buyer_links(buyer.id, limit=MAX_LINKS_IN_KEYBOARD)
        if not links:
            await self.telegram.send_message(
                chat_id,
                "Сначала создай ссылку через «Создать ссылку».",
                reply_markup=MAIN_MENU_MARKUP,
            )
            return

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": link.title or link.name,
                        "callback_data": f"spend_link:{link.id}",
                    }
                ]
                for link in links
            ]
        }
        await self.state_store.set(chat_id, {"state": STATE_SPEND_DATE})
        await self.telegram.send_message(chat_id, "Выбери ссылку для внесения расхода:", reply_markup=keyboard)

    async def _select_spend_link(self, chat_id: int, buyer: User, raw_link_id: str) -> None:
        link_id = self._parse_uuid(raw_link_id)
        if link_id is None:
            await self.telegram.send_message(chat_id, "Ссылка не найдена.", reply_markup=MAIN_MENU_MARKUP)
            return

        link = await self._get_buyer_link(link_id, buyer.id)
        if link is None:
            await self.telegram.send_message(chat_id, "Ссылка не найдена.", reply_markup=MAIN_MENU_MARKUP)
            return

        await self.state_store.set(
            chat_id,
            {"state": STATE_SPEND_DATE, "link_id": str(link.id)},
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Сегодня", "callback_data": "spend_date:today"},
                    {"text": "Вчера", "callback_data": "spend_date:yesterday"},
                ]
            ]
        }
        await self.telegram.send_message(
            chat_id,
            f"Дата расхода для ссылки «{link.title or link.name}»:",
            reply_markup=keyboard,
        )

    async def _select_spend_date(self, chat_id: int, buyer: User, value: str) -> None:
        state = await self.state_store.get(chat_id)
        link_id = self._parse_uuid((state or {}).get("link_id"))
        if link_id is None:
            await self.telegram.send_message(
                chat_id,
                "Сначала выбери ссылку через «Ввести расход».",
                reply_markup=MAIN_MENU_MARKUP,
            )
            return

        link = await self._get_buyer_link(link_id, buyer.id)
        if link is None:
            await self.telegram.send_message(chat_id, "Ссылка не найдена.", reply_markup=MAIN_MENU_MARKUP)
            return

        if value == "today":
            spend_date = date.today()
        elif value == "yesterday":
            spend_date = date.today() - timedelta(days=1)
        else:
            await self.telegram.send_message(chat_id, "Дата не распознана.", reply_markup=MAIN_MENU_MARKUP)
            return

        await self.state_store.set(
            chat_id,
            {
                "state": STATE_SPEND_AMOUNT,
                "link_id": str(link.id),
                "spend_date": spend_date.isoformat(),
            },
        )
        await self.telegram.send_message(
            chat_id,
            f"Пришли сумму расхода за {spend_date.isoformat()} по ссылке «{link.title or link.name}».",
        )

    async def _finish_spend(
        self,
        chat_id: int,
        buyer: User,
        state: dict[str, Any],
        raw_amount: str,
    ) -> None:
        link_id = self._parse_uuid(state.get("link_id"))
        spend_date = self._parse_date(state.get("spend_date"))
        amount = self._parse_positive_decimal(raw_amount)
        if link_id is None or spend_date is None:
            await self.telegram.send_message(
                chat_id,
                "Контекст расхода устарел. Начни заново через «Ввести расход».",
                reply_markup=MAIN_MENU_MARKUP,
            )
            await self.state_store.clear(chat_id)
            return
        if amount is None:
            await self.telegram.send_message(chat_id, "Пришли положительное число, например 240 или 180.50.")
            return

        link = await self._get_buyer_link(link_id, buyer.id)
        if link is None:
            await self.telegram.send_message(chat_id, "Ссылка не найдена.", reply_markup=MAIN_MENU_MARKUP)
            await self.state_store.clear(chat_id)
            return

        existing_result = await self.db.execute(
            select(TrackingSpend)
            .where(
                TrackingSpend.tracking_link_id == link.id,
                TrackingSpend.spend_date == spend_date,
            )
            .order_by(TrackingSpend.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        existing = existing_result.scalar_one_or_none()
        if existing is None:
            self.db.add(
                TrackingSpend(
                    tracking_link_id=link.id,
                    spend_date=spend_date,
                    amount=amount,
                    currency="USD",
                    source=TrackingSpendSource.BUYER_BOT,
                    created_by_user_id=buyer.id,
                )
            )
        else:
            await self.db.execute(
                update(TrackingSpend)
                .where(TrackingSpend.id == existing.id)
                .values(
                    amount=amount,
                    currency="USD",
                    source=TrackingSpendSource.BUYER_BOT,
                    created_by_user_id=buyer.id,
                    updated_at=func.now(),
                )
            )

        await self.db.commit()
        await self.state_store.clear(chat_id)
        await self.telegram.send_message(
            chat_id,
            f"Расход сохранен: {money(amount)} USD за {spend_date.isoformat()}.\n"
            f"Ссылка: {link.title or link.name}",
            reply_markup=MAIN_MENU_MARKUP,
        )

    async def _send_stats(self, chat_id: int, buyer: User) -> None:
        today = date.today()
        periods = [
            ("Сегодня", today, today),
            ("Вчера", today - timedelta(days=1), today - timedelta(days=1)),
            ("7 дней", today - timedelta(days=6), today),
        ]
        stats = [
            await self._get_buyer_period_stats(buyer.id, label, date_from, date_to)
            for label, date_from, date_to in periods
        ]

        lines = ["Статистика по твоим ссылкам:"]
        for item in stats:
            lines.append(
                f"{item.label}\n"
                f"Расход: ${money(item.spend)} | Лиды: {item.leads} | "
                f"CPL: ${item.cpl} | CR в лиды: {item.lead_conversion_percent}%"
            )
        await self.telegram.send_message(chat_id, "\n\n".join(lines), reply_markup=MAIN_MENU_MARKUP)

    async def _send_funnel(self, chat_id: int, buyer: User) -> None:
        steps = await self._get_buyer_funnel_dropoff(buyer.id)
        if not steps:
            await self.telegram.send_message(
                chat_id,
                "По твоему трафику пока нет данных прохождения воронки.",
                reply_markup=MAIN_MENU_MARKUP,
            )
            return

        lines = ["Воронка отвалов по твоим ссылкам:"]
        for step in steps:
            marker = "" if step.position == 1 else f" 🔻 -{step.dropoff_percent}%"
            lines.append(
                f"{step.position}. {step.title}: {step.count} ({step.reached_percent}%){marker}"
            )
        await self.telegram.send_message(chat_id, "\n".join(lines), reply_markup=MAIN_MENU_MARKUP)

    async def _require_buyer(self, chat_id: int) -> User | None:
        buyer = await self._get_buyer_by_telegram_id(chat_id)
        if buyer is None:
            await self.telegram.send_message(
                chat_id,
                "Аккаунт не привязан. Открой инвайт-ссылку от администратора.",
            )
            return None
        return buyer

    async def _get_buyer_by_telegram_id(self, chat_id: int) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.buyer_telegram_id == chat_id,
                User.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def _resolve_client_bot(self, project_id: UUID) -> Bot | None:
        stmt = select(Bot).where(
            Bot.project_id == project_id,
            Bot.is_deleted.is_(False),
            Bot.bot_username.is_not(None),
        )
        username = (settings.CLIENT_BOT_USERNAME or "").removeprefix("@").strip()
        if username:
            stmt = stmt.where(
                func.lower(func.replace(Bot.bot_username, "@", "")) == username.lower()
            )
        else:
            stmt = stmt.order_by(Bot.active_funnel_version_id.is_(None), Bot.created_at.asc())
        result = await self.db.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def _list_buyer_links(self, buyer_id: UUID, limit: int) -> list[TrackingLink]:
        result = await self.db.execute(
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(
                TrackingLink.buyer_id == buyer_id,
                TrackingLink.is_active.is_(True),
            )
            .order_by(TrackingLink.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _get_buyer_link(self, link_id: UUID, buyer_id: UUID) -> TrackingLink | None:
        result = await self.db.execute(
            select(TrackingLink).where(
                TrackingLink.id == link_id,
                TrackingLink.buyer_id == buyer_id,
                TrackingLink.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def _generate_unique_ref_code(self) -> str:
        alphabet = string.ascii_letters + string.digits
        for _ in range(20):
            code = "".join(secrets.choice(alphabet) for _ in range(REF_CODE_LENGTH))
            existing = await self.db.execute(
                select(TrackingLink.id)
                .where((TrackingLink.code == code) | (TrackingLink.ref_code == code))
                .limit(1)
            )
            if existing.scalar_one_or_none() is None:
                return code
        raise RuntimeError("Could not generate unique tracking ref code")

    async def _get_buyer_period_stats(
        self,
        buyer_id: UUID,
        label: str,
        date_from: date,
        date_to: date,
    ) -> BuyerPeriodStats:
        start_at, end_at = date_bounds(date_from, date_to)

        spend_result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0))
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingLink.buyer_id == buyer_id,
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
        )
        spend = Decimal(spend_result.scalar_one() or 0)

        leads_result = await self.db.execute(
            select(func.count(distinct(Lead.id)))
            .join(Chat, Chat.id == Lead.chat_id)
            .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .where(
                TrackingLink.buyer_id == buyer_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                func.coalesce(Chat.current_cycle_started_at, Lead.created_at) >= start_at,
                func.coalesce(Chat.current_cycle_started_at, Lead.created_at) < end_at,
            )
        )
        leads = int(leads_result.scalar_one() or 0)

        clicks_result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingEvent.clicks), 0))
            .join(TrackingLink, TrackingLink.id == TrackingEvent.tracking_link_id)
            .where(
                TrackingLink.buyer_id == buyer_id,
                TrackingEvent.created_at >= start_at,
                TrackingEvent.created_at < end_at,
            )
        )
        clicks = int(clicks_result.scalar_one() or 0)
        return BuyerPeriodStats(label=label, spend=spend, leads=leads, clicks=clicks)

    async def _get_buyer_funnel_dropoff(self, buyer_id: UUID) -> list[BuyerFunnelStepStats]:
        result = await self.db.execute(
            select(
                FunnelStepLog.step_id.label("step_id"),
                func.coalesce(FunnelStep.title, FunnelStepLog.step_name).label("step_title"),
                FunnelStep.position_x.label("position_x"),
                FunnelStep.position_y.label("position_y"),
                func.min(FunnelStepLog.created_at).label("first_seen_at"),
                func.count(distinct(FunnelStepLog.lead_id)).label("lead_count"),
            )
            .join(Lead, Lead.id == FunnelStepLog.lead_id)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .outerjoin(FunnelStep, FunnelStep.id == FunnelStepLog.step_id)
            .where(
                TrackingLink.buyer_id == buyer_id,
                FunnelStepLog.event_type == "entered",
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .group_by(
                FunnelStepLog.step_id,
                FunnelStep.title,
                FunnelStepLog.step_name,
                FunnelStep.position_x,
                FunnelStep.position_y,
            )
            .order_by(
                FunnelStep.position_x.asc().nullslast(),
                FunnelStep.position_y.asc().nullslast(),
                func.min(FunnelStepLog.created_at).asc(),
            )
        )
        rows = result.mappings().all()
        if not rows:
            return []

        first_count = int(rows[0]["lead_count"] or 0)
        previous_count = first_count
        stats: list[BuyerFunnelStepStats] = []
        for index, row in enumerate(rows, start=1):
            count = int(row["lead_count"] or 0)
            reached_percent = percent(
                Decimal(count) / Decimal(first_count) * Decimal("100")
                if first_count
                else Decimal("0")
            )
            dropoff_percent = Decimal("0.00")
            if index > 1 and previous_count > 0:
                dropoff_percent = percent(
                    Decimal(max(previous_count - count, 0))
                    / Decimal(previous_count)
                    * Decimal("100")
                )
            stats.append(
                BuyerFunnelStepStats(
                    position=index,
                    title=str(row["step_title"] or row["step_id"]),
                    count=count,
                    reached_percent=reached_percent,
                    dropoff_percent=dropoff_percent,
                )
            )
            previous_count = count
        return stats

    @staticmethod
    def _normalize_activation_token(raw_token: str) -> UUID | None:
        token = raw_token.strip()
        if token.startswith("act_"):
            token = token.removeprefix("act_")
        return BuyerBotService._parse_uuid(token)

    @staticmethod
    def _normalize_link_title(raw_title: str) -> str | None:
        title = re.sub(r"\s+", " ", raw_title).strip()
        if len(title) < 2:
            return None
        return title[:255]

    @staticmethod
    def _build_client_start_link(bot_username: str | None, code: str | None) -> str:
        username = (bot_username or "").removeprefix("@").strip()
        ref_code = (code or "").strip()
        return f"https://t.me/{username}?start=ref_{ref_code}"

    @staticmethod
    def _split_command(text: str) -> tuple[str, str | None]:
        parts = text.strip().split(maxsplit=1)
        command = parts[0] if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else None
        return command, argument

    @staticmethod
    def _is_start_command(command: str) -> bool:
        return command == "/start" or command.startswith("/start@")

    @staticmethod
    def _callback_chat_id(callback_query: TelegramCallbackQuery) -> int | None:
        if callback_query.message is not None:
            return callback_query.message.chat.id
        if callback_query.from_user is not None:
            return callback_query.from_user.id
        return None

    @staticmethod
    def _parse_uuid(value: Any) -> UUID | None:
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_positive_decimal(value: str) -> Decimal | None:
        normalized = value.strip().replace(",", ".")
        try:
            amount = Decimal(normalized)
        except (InvalidOperation, ValueError):
            return None
        if amount <= 0:
            return None
        return money(amount)


def date_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
    return start_at, end_at


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
