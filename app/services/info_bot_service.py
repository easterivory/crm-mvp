"""Super-admin-only, read-only Telegram tracking workspace."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import RoleName
from app.core.telegram_links import canonicalize_telegram_web_link
from app.models.bot import Bot
from app.models.channel_tracking import TelegramChannelInviteLink
from app.models.lander import ProjectLander
from app.models.project import Project
from app.models.role import Role
from app.models.tracking import TrackingLink
from app.models.user import User
from app.services.buyer_bot_service import BuyerBotStateStore
from app.services.info_bot_reports import InfoBotReports, format_summary, parse_custom_period, period_bounds

PAGE_SIZE = 8
MAX_LINKS = 20


class InfoBotStateStore(BuyerBotStateStore):
    @staticmethod
    def _key(telegram_chat_id: int) -> str:
        return f"info_bot:fsm:{telegram_chat_id}"


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": title[:60], "callback_data": value} for title, value in row] for row in rows]}


def period_keyboard() -> dict:
    return keyboard([
        [("Эта неделя", "period:week:0"), ("Прошлая неделя", "period:week:-1")],
        [("Этот месяц", "period:month:0"), ("Прошлый месяц", "period:month:-1")],
        [("Всё время", "period:all:0"), ("Свои даты", "custom")],
        [("Проекты", "projects:0"), ("Боты", "bots:0"), ("Ссылки", "links:0")],
    ])


class InfoBotService:
    def __init__(self, db: AsyncSession, state: InfoBotStateStore):
        self.db = db
        self.state_store = state

    async def authorized_user(self, telegram_id: int) -> User | None:
        return await self.db.scalar(select(User).options(selectinload(User.role)).where(
            User.telegram_id == telegram_id, User.is_deleted.is_(False),
            User.role.has(Role.name == RoleName.SUPER_ADMIN)))

    async def handle_update(self, update: dict) -> tuple[int | None, list[dict]]:
        callback = update.get("callback_query") or {}
        message = callback.get("message") or update.get("message") or {}
        sender = callback.get("from") or message.get("from") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat.get("type") != "private" or not isinstance(chat_id, int) or sender.get("id") != chat_id:
            return None, []
        if not await self.authorized_user(chat_id):
            await self.state_store.clear(chat_id)
            return chat_id, [{"text": "Доступ только для суперадминистраторов CRM с привязанным Telegram ID."}]
        state = await self.state_store.get(chat_id) or {}
        data = callback.get("data")
        text = str(message.get("text") or "").strip() if not callback else ""
        try:
            if data:
                return chat_id, await self.callback(chat_id, str(data), state)
            if text.split("@", 1)[0] in {"/start", "/stats", "/projects", "/cancel"}:
                await self.state_store.clear(chat_id)
                return chat_id, await self.catalog("projects", 0, {})
            if state.get("awaiting_dates"):
                start, end = parse_custom_period(text)
                state.update(start=start.isoformat(), end=end.isoformat(), kind="custom", awaiting_dates=False)
                await self.state_store.set(chat_id, state)
                return chat_id, await self.report(state)
            if text:
                inputs = list(dict.fromkeys(text.split()))
                if len(inputs) > MAX_LINKS:
                    raise ValueError(f"За один запрос можно прислать до {MAX_LINKS} ссылок.")
                links, missing, projects = [], [], set()
                for value in inputs:
                    link = await self.resolve_link(value)
                    if link is None:
                        missing.append(value[:150])
                    elif str(link.id) not in links:
                        links.append(str(link.id))
                        projects.add(str(link.project_id))
                if not links:
                    raise ValueError("Не найдены ссылки Сферы. Пришлите трек-ссылку, Telegram-ссылку с start или ссылку на лендинг.")
                state = {"link_ids": links, "kind": "week", "offset": 0}
                if len(projects) == 1:
                    state["project_id"] = next(iter(projects))
                await self.state_store.set(chat_id, state)
                weekly = await self.report(state)
                all_time = await self.report({**state, "kind": "all"})
                replies = [{"text": week["text"] + "\n\n━━━━━━━━━━━━\n\n" + total["text"]}
                           for week, total in zip(weekly, all_time, strict=True)]
                replies[-1]["reply_markup"] = weekly[-1]["reply_markup"]
                if missing:
                    replies.append({"text": "Не распознаны:\n" + "\n".join(missing)})
                return chat_id, replies
            return chat_id, [{"text": "Выберите проект или пришлите одну ссылку либо список ссылок.", "reply_markup": period_keyboard()}]
        except (ValueError, OverflowError) as exc:
            return chat_id, [{"text": str(exc), "reply_markup": period_keyboard()}]

    async def callback(self, chat_id: int, data: str, state: dict) -> list[dict]:
        action, _, value = data.partition(":")
        if action in {"projects", "bots", "links"}:
            page = max(0, min(int(value), 10000))
            return await self.catalog(action, page, state)
        if action == "project":
            project = await self.project(UUID(value))
            if not project:
                raise ValueError("Проект не найден.")
            state = {"project_id": str(project.id), "kind": "week", "offset": 0}
        elif action == "bot":
            bot = await self.db.get(Bot, UUID(value))
            if not bot or bot.is_deleted or str(bot.project_id) != state.get("project_id"):
                raise ValueError("Бот не найден в выбранном проекте.")
            state.pop("link_ids", None)
            state["bot_id"] = str(bot.id)
        elif action == "link":
            link = await self.db.get(TrackingLink, UUID(value))
            if not link or str(link.project_id) != state.get("project_id"):
                raise ValueError("Ссылка не найдена в выбранном проекте.")
            state["link_ids"] = [str(link.id)]
            state.pop("bot_id", None)
        elif action == "allbots":
            state.pop("bot_id", None)
            state.pop("link_ids", None)
        elif action == "period":
            kind, offset = value.split(":")
            offset = int(offset)
            if offset > 0 or offset < -120:
                raise ValueError("Период вне допустимого диапазона.")
            period_bounds(kind, offset)
            state.update(kind=kind, offset=offset, awaiting_dates=False)
        elif action == "custom":
            if not state.get("project_id") and not state.get("link_ids"):
                raise ValueError("Сначала выберите проект или пришлите ссылки.")
            state["awaiting_dates"] = True
            await self.state_store.set(chat_id, state)
            return [{"text": "Введите начало и конец: 01.10.2026 11.10.2026. Даты включительно, время московское.",
                     "reply_markup": keyboard([[("Отмена", "period:week:0")]])}]
        else:
            raise ValueError("Кнопка устарела. Откройте /stats.")
        await self.state_store.set(chat_id, state)
        return await self.report(state)

    async def project(self, project_id: UUID) -> Project | None:
        return await self.db.scalar(select(Project).where(Project.id == project_id, Project.is_deleted.is_(False)))

    async def catalog(self, kind: str, page: int, state: dict) -> list[dict]:
        if kind == "projects":
            query = select(Project).where(Project.is_deleted.is_(False)).order_by(Project.name, Project.id)
            title = "Проекты"
        else:
            if not state.get("project_id"):
                raise ValueError("Сначала выберите проект.")
            project = await self.project(UUID(state["project_id"]))
            if project is None:
                raise ValueError("Проект не найден.")
            if kind == "bots":
                query = select(Bot).where(Bot.project_id == project.id, Bot.is_deleted.is_(False)).order_by(Bot.name, Bot.id)
            else:
                query = select(TrackingLink).where(TrackingLink.project_id == project.id).order_by(TrackingLink.title, TrackingLink.id)
                if state.get("bot_id"):
                    query = query.where(TrackingLink.bot_id == UUID(state["bot_id"]))
            title = f"{project.name}: {'боты' if kind == 'bots' else 'ссылки'}"
        items = list((await self.db.scalars(query.offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1))).all())
        action = {"projects": "project", "bots": "bot", "links": "link"}[kind]
        rows = [[(item.title if kind == "links" else item.name, f"{action}:{item.id}")] for item in items[:PAGE_SIZE]]
        navigation = []
        if page:
            navigation.append(("Предыдущие", f"{kind}:{page - 1}"))
        if len(items) > PAGE_SIZE:
            navigation.append(("Следующие", f"{kind}:{page + 1}"))
        if navigation:
            rows.append(navigation)
        if kind != "projects":
            rows.append([("Весь проект", "allbots"), ("Проекты", "projects:0")])
        return [{"text": title if items else title + ": список пуст", "reply_markup": keyboard(rows)}]

    async def resolve_link(self, value: str) -> TrackingLink | None:
        value = value.strip("<>(),;")
        parsed = urlsplit(value if "://" in value else "https://" + value)
        path = unquote(parsed.path).strip("/").split("/")
        query = parse_qs(parsed.query)
        if parsed.hostname in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"} and query.get("start"):
            code = query["start"][-1]
            return await self.db.scalar(select(TrackingLink).join(Bot, Bot.id == TrackingLink.bot_id).where(
                or_(TrackingLink.code == code, TrackingLink.ref_code == code),
                func.lower(Bot.bot_username) == path[0].lower()))
        if len(path) >= 2 and path[-2] in {"join", "track", "r", "t"}:
            return await self.db.scalar(select(TrackingLink).where(or_(TrackingLink.code == path[-1], TrackingLink.ref_code == path[-1])))
        canonical = canonicalize_telegram_web_link(value)
        aliases = {value, canonical}
        if canonical and canonical.startswith("https://telegram.me/"):
            aliases.add(canonical.replace("https://telegram.me/", "https://t.me/", 1))
        invite = await self.db.scalar(select(TrackingLink).where(TrackingLink.invite_link.in_(aliases)))
        if invite:
            return invite
        invite = await self.db.scalar(select(TrackingLink).join(TelegramChannelInviteLink,
            TelegramChannelInviteLink.tracking_link_id == TrackingLink.id)
            .where(TelegramChannelInviteLink.invite_link.in_(aliases)))
        if invite:
            return invite
        slug = path[-1]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug):
            return None
        return await self.db.scalar(select(TrackingLink).join(ProjectLander, ProjectLander.tracking_link_id == TrackingLink.id)
            .where(ProjectLander.slug == slug))

    async def report(self, state: dict) -> list[dict]:
        kind = state.get("kind", "week")
        start, end = (date.fromisoformat(state["start"]), date.fromisoformat(state["end"])) if kind == "custom" else period_bounds(kind, state.get("offset", 0))
        heading = "Всё время" if kind == "all" else f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"
        if kind == "week":
            heading = "Неделя (пн–вс): " + heading
        elif kind == "month":
            heading = "Месяц: " + heading
        targets = []
        for link_id in state.get("link_ids", []):
            link = await self.db.get(TrackingLink, UUID(link_id))
            if not link:
                raise ValueError("Одна из ссылок удалена. Пришлите список заново.")
            project = await self.project(link.project_id)
            if not project:
                raise ValueError("Проект ссылки удалён.")
            targets.append((project, link, None, f"{project.name} / {link.title}\nКод: {link.code}"))
        if not targets:
            if not state.get("project_id"):
                raise ValueError("Сначала выберите проект или пришлите ссылки.")
            project = await self.project(UUID(state["project_id"]))
            if not project:
                raise ValueError("Проект не найден.")
            bot_id = UUID(state["bot_id"]) if state.get("bot_id") else None
            title = project.name
            if bot_id:
                bot = await self.db.get(Bot, bot_id)
                if not bot or bot.is_deleted or bot.project_id != project.id:
                    raise ValueError("Бот не найден.")
                title += " / " + bot.name
            targets.append((project, None, bot_id, title))
        reports, total, destinations = [], {}, set()
        for project, link, bot_id, title in targets:
            values = await InfoBotReports(self.db).summary(project, start, end, link, bot_id)
            destinations.add(values["destination_type"])
            for key, value in values.items():
                if key == "destination_type":
                    continue
                total[key] = total.get(key, 0) + value
            reports.append({"text": f"{title}\n{heading} · МСК\n\n" + format_summary(values, gambling=project.project_format == "gambling")})
        if len(targets) > 1:
            total["destination_type"] = next(iter(destinations)) if len(destinations) == 1 else "mixed"
            reports.append({"text": f"Итого по {len(targets)} ссылкам\n{heading} · МСК\n\n" + format_summary(total, gambling=all(project.project_format == "gambling" for project, _, _, _ in targets)) + "\nСумма показателей ссылок, не уникальные люди между ссылками."})
        rows = period_keyboard()["inline_keyboard"]
        if kind in {"week", "month"}:
            offset = state.get("offset", 0)
            navigation = [("Предыдущий период", f"period:{kind}:{offset - 1}")]
            if offset < 0:
                navigation.append(("Следующий период", f"period:{kind}:{offset + 1}"))
            rows = keyboard([navigation])["inline_keyboard"] + rows
        reports[-1]["reply_markup"] = {"inline_keyboard": rows}
        return reports
