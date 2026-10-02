"""Buyer-facing tracking screens built on the same services as the CRM."""
from datetime import date, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, func

from app.core.config import settings
from app.models.bot import Bot
from app.models.lander import ProjectDomain, ProjectLander
from app.models.tracking import TrackingLink
from app.models.traffic_quality import TrafficQualityState
from app.models.tag import Tag
from app.schemas.tracking import TrackingLinkCreate
from app.schemas.lander import ProjectLanderCreate, LanderTrackingCampaignCreate
from app.services.access_control import require_project_access
from app.services.tracking_metrics_service import TrackingMetricsService
from app.services.tracking_service import TrackingService
from app.services.channel_tracking_service import ChannelTrackingService
from app.services.lander_admin_service import LanderAdminService
from app.services.lander_service import LanderService
from app.services.traffic_quality_service import TrafficQualityService
from app.services.telegram_chart_service import render_stats_chart


def markup(rows):
    return {"inline_keyboard": [[{"text": title[:60], "callback_data": data} for title, data in row] for row in rows]}


class BuyerTrackingWorkspace:
    def __init__(self, service):
        self.owner = service
        self.db, self.telegram, self.store = service.db, service.telegram, service.state_store

    async def send(self, chat_id, text, rows=()):
        await self.db.commit()
        await self.telegram.send_message(chat_id, text, reply_markup=markup([*rows, [("Меню", "menu:cancel")]]))

    @staticmethod
    def summary(metrics, project_format):
        lines = [f"Клики: {metrics.clicks} · Старты: {metrics.starts} · Лиды: {metrics.leads}"]
        if project_format == "gambling":
            lines.append(f"Регистрации: {metrics.registrations} · ФД: {metrics.first_deposits} · РД: {metrics.redeposits}")
        else:
            lines.append(f"Подано: {metrics.submitted_leads}")
        lines.append(f"Канал: заявок {metrics.channel_join_requests}, подписок {metrics.channel_joins}, отписок {metrics.channel_leaves}")
        lines.append(f"Расход: {metrics.spend} USD · CPL: {metrics.cpl if metrics.leads and metrics.spend else '—'}")
        if project_format == "gambling":
            lines.append(f"Цена регистрации: {metrics.cpr if metrics.registrations and metrics.spend else '—'} · Цена ФД: {metrics.cpfd if metrics.first_deposits and metrics.spend else '—'}")
        else:
            lines.append(f"Цена подачи: {metrics.cpsl if metrics.submitted_leads and metrics.spend else '—'}")
        return "\n".join(lines)

    async def stats(self, chat_id, buyer, project_id, days=7, link_id=None, chart=False):
        require_project_access(buyer, project_id)
        # Existing CRM activity analytics uses UTC calendar days, not the cohort
        # window used by quality rules. Keep the same boundaries in both UIs.
        from datetime import datetime, timezone
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days - 1)
        service = TrackingMetricsService(self.db)
        data = await service.get_link_metrics(buyer, link_id, date_from=start, date_to=end) if link_id else await service.get_project_metrics(buyer, project_id, date_from=start, date_to=end)
        title = data.title if link_id else "Мои ссылки"
        if chart:
            gambling = data.project_format == "gambling"
            photo = render_stats_chart(title=title, labels=[row.date.strftime("%d.%m") for row in data.daily],
                leads=[row.registrations if gambling else row.leads for row in data.daily],
                submitted=[row.first_deposits if gambling else row.submitted_leads for row in data.daily],
                spend=[float(row.spend) for row in data.daily], primary_label="Регистрации" if gambling else "Лиды",
                secondary_label="ФД" if gambling else "Подано")
            await self.db.commit()
            await self.telegram.send_photo(chat_id, photo, caption=f"{title}: {start} — {end}, UTC. События за период.")
            return
        suffix = str(link_id) if link_id else "project"
        rows = [[("Сегодня", f"bw:stats:1:{suffix}"), ("7 дней", f"bw:stats:7:{suffix}"), ("30 дней", f"bw:stats:30:{suffix}")],
                [("График", f"bw:chart:{days}:{suffix}"), ("Алерты", "menu:quality")]]
        if link_id:
            link = await TrackingService(self.db).get_tracking_link(link_id, buyer)
            landers = await LanderAdminService(self.db).list_landers(project_id=project_id, actor=buyer)
            lander = next((item for item in landers if item.is_active and item.tracking_link_id == link_id), None)
            url = lander.public_url if lander else link.tracking_url or link.invite_link or link.code
            title += f"\n{url}"
            rows.append([("Теги", f"bw:tags:{link_id}:0"), ("Расход", f"spend_link:{link_id}")])
        await self.send(chat_id, f"{title}\n{start} — {end} (UTC)\nСобытия за период\n\n{self.summary(data.summary, data.project_format)}", rows)

    async def links(self, chat_id, buyer, project_id, offset=0, search=""):
        require_project_access(buyer, project_id)
        stmt = select(TrackingLink).where(TrackingLink.project_id == project_id, TrackingLink.buyer_id == buyer.id, TrackingLink.is_active.is_(True))
        if search:
            stmt = stmt.where(TrackingLink.title.icontains(search, autoescape=True) | TrackingLink.code.icontains(search, autoescape=True))
        links = (await self.db.scalars(stmt.order_by(TrackingLink.created_at.desc(), TrackingLink.id).offset(offset).limit(11))).all()
        state = await self.store.get(chat_id) or {}
        state.update(project_id=str(project_id), link_search=search)
        await self.store.set(chat_id, state)
        quality = await TrafficQualityService(self.db).config(project_id)
        problematic = set()
        if quality.enabled and links:
            problematic = set((await self.db.scalars(select(TrafficQualityState.link_id).where(
                TrafficQualityState.link_id.in_([link.id for link in links[:10]]),
                TrafficQualityState.active.is_(True),
                TrafficQualityState.status != "disabled",
            ))).all())
        rows = [[(f"{'Алерт · ' if link.id in problematic else ''}{'Канал' if link.destination_type == 'channel' else 'Бот'} · {link.title}", f"bw:stats:7:{link.id}")] for link in links[:10]]
        pages = []
        if offset:
            pages.append(("Назад", f"bw:links:{max(0, offset - 10)}"))
        if len(links) > 10:
            pages.append(("Далее", f"bw:links:{offset + 10}"))
        if pages:
            rows.append(pages)
        rows.append([("Поиск", "bw:search"), ("Сбросить поиск", "bw:clear")])
        await self.send(chat_id, "Мои ссылки" + (f" · {search}" if search else "") + ("\nСсылок не найдено" if not links else ""), rows)

    async def alerts(self, chat_id, buyer, project_id, offset=0):
        require_project_access(buyer, project_id)
        config = await TrafficQualityService(self.db).config(project_id)
        rows = (await self.db.execute(select(TrafficQualityState, TrackingLink.title).join(TrackingLink, TrackingLink.id == TrafficQualityState.link_id).where(
            TrackingLink.project_id == project_id, TrackingLink.buyer_id == buyer.id, TrackingLink.is_active.is_(True),
        ).order_by(TrafficQualityState.active.desc(), TrafficQualityState.checked_at.desc(), TrafficQualityState.rule_id).offset(offset).limit(6))).all()
        labels = {"alert": "Нарушение", "breach": "Ожидает подтверждения", "normal": "Норма", "insufficient_data": "Мало данных", "disabled": "Отключено", "configuration_error": "Ошибка настройки"}
        text, keyboard = [f"Контроль качества: {'включён' if config.enabled else 'выключен'}"], []
        for item, title in rows[:5]:
            s = item.snapshot
            value = s.get("value")
            text.append(f"{title} · {s.get('rule_name', 'Правило')}\n{labels.get(item.status, item.status)}: {value if value is not None else '—'}\n{s.get('reason') or s.get('expression', '')}")
            keyboard.append([(f"Статистика: {title}", f"quality:stats:{item.link_id}")])
        if len(rows) > 5:
            keyboard.append([("Далее", f"bw:alerts:{offset + 5}")])
        await self.send(chat_id, "\n\n".join(text) if rows else "Проверок пока нет", keyboard)

    async def start(self, chat_id, buyer, project_id, facebook=False):
        require_project_access(buyer, project_id)
        state = {"project_id": str(project_id), "state": "bw:destination", "nonce": uuid4().hex[:12], "facebook": facebook}
        await self.store.set(chat_id, state)
        await self.choose(chat_id, state, "Куда ведёт ссылка?", [("Бот", "bot"), ("Канал", "channel")])

    async def choose(self, chat_id, state, title, options, offset=0):
        state["nonce"] = uuid4().hex[:12]
        state["options"] = options
        state["choice_title"] = title
        state["choice_offset"] = offset
        await self.store.set(chat_id, state)
        rows = [[(name, f"bw:pick:{state['nonce']}:{index}")] for index, (name, _) in enumerate(options) if offset <= index < offset + 10]
        pages = []
        if offset:
            pages.append(("Назад", f"bw:page:{state['nonce']}:{max(0, offset - 10)}"))
        if offset + 10 < len(options):
            pages.append(("Далее", f"bw:page:{state['nonce']}:{offset + 10}"))
        if pages:
            rows.append(pages)
        await self.send(chat_id, title if options else f"{title}\nНет доступных вариантов. Обратитесь к администратору проекта.", rows)

    async def pick(self, chat_id, buyer, state, value):
        project_id = UUID(state["project_id"])
        require_project_access(buyer, project_id)
        stage = state["state"]
        if stage == "bw:destination":
            state.update(destination=value, state="bw:target")
            if value == "channel":
                channels = await ChannelTrackingService(self.db).list_channels(project_id=project_id, actor=buyer)
                options = [(item.title, str(item.id)) for item in channels if item.bot_is_admin and item.can_invite_users]
            else:
                bots = (await self.db.scalars(select(Bot).where(Bot.project_id == project_id, Bot.is_deleted.is_(False), Bot.transport_type != "user_mtproto"))).all()
                options = [(item.name, str(item.id)) for item in bots]
            await self.choose(chat_id, state, "Выберите канал" if value == "channel" else "Выберите бота", options)
        elif stage == "bw:target":
            state.update(target=value, state="bw:name")
            await self.store.set(chat_id, state)
            await self.send(chat_id, "Название ссылки:")
        elif stage == "bw:mode":
            state["facebook"] = value == "facebook"
            if state["facebook"]:
                domains = (await self.db.scalars(select(ProjectDomain).where(ProjectDomain.project_id == project_id, ProjectDomain.is_active.is_(True)).order_by(ProjectDomain.domain_name))).all()
                state["state"] = "bw:domain"
                options = [(item.domain_name, str(item.id)) for item in domains]
                if settings.LANDER_TECH_DOMAIN:
                    options.insert(0, (f"Технический: {settings.LANDER_TECH_DOMAIN}", "tech"))
                await self.choose(chat_id, state, "Домен кампании:", options)
            else:
                await self.confirm(chat_id, state, buyer)
        elif stage == "bw:domain":
            state.update(domain=value, state="bw:template")
            landers = await LanderAdminService(self.db).list_landers(project_id=project_id, actor=buyer)
            await self.choose(chat_id, state, "Оформление лендинга:", [("Стандартный", "default")] + [(item.name, str(item.id)) for item in landers if item.is_active and (item.type == "default_tg_redirect" or item.custom_html_path)])
        elif stage == "bw:template":
            state.update(template=value, state="bw:redirect")
            await self.choose(chat_id, state, "Автоматический переход с лендинга:", [("Нет, по кнопке", "off"), ("Да", "on")])
        elif stage == "bw:redirect":
            state["redirect"] = value == "on"
            await self.confirm(chat_id, state, buyer)

    async def confirm(self, chat_id, state, buyer):
        state["state"] = "bw:confirm"
        state["nonce"] = uuid4().hex[:12]
        state["options"] = []
        await self.store.set(chat_id, state)
        details = f"Создать: {state['title']}\nНазначение: {'канал (заявка)' if state['destination'] == 'channel' else 'бот'}\nТип: {'Facebook с лендингом' if state.get('facebook') else 'Прямая ссылка'}"
        if state.get("facebook"):
            details += f"\nPixel: {buyer.buyer_fb_pixel_id or 'не настроен'}\nCAPI: {'настроен' if buyer.buyer_fb_capi_token else 'не настроен'}"
        await self.send(chat_id, details, [[("Создать", f"bw:confirm:{state['nonce']}")]])

    async def finish(self, chat_id, buyer, nonce):
        lock = self.store.redis.lock(f"buyer:link-create:{buyer.id}", timeout=120, blocking_timeout=0)
        if not await lock.acquire(blocking=False):
            await self.send(chat_id, "Ссылка уже создаётся. Подождите завершения.")
            return
        try:
            state = await self.store.get(chat_id) or {}
            if state.get("state") != "bw:confirm" or state.get("nonce") != nonce:
                await self.send(chat_id, "Эта форма уже завершена или устарела. Откройте «Мои ссылки».")
                return
            project_id = UUID(state["project_id"])
            require_project_access(buyer, project_id)
            code = f"b{nonce}"
            existing = await self.db.scalar(select(TrackingLink).where(TrackingLink.code == code))
            if existing and (existing.project_id != project_id or existing.buyer_id != buyer.id):
                raise HTTPException(409, "Код занят. Создайте новую форму ссылки")
            if not existing:
                destination = {"destination_type": state["destination"], "title": state["title"], "code": code,
                               "channel_join_request": state["destination"] == "channel"}
                destination["bot_id" if state["destination"] == "bot" else "channel_id"] = UUID(state["target"])
                if state.get("facebook"):
                    content = {}
                    template = None
                    if state.get("template") not in (None, "default"):
                        templates = await LanderAdminService(self.db).list_landers(project_id=project_id, actor=buyer)
                        template = next((t for t in templates if str(t.id) == state["template"] and t.is_active), None)
                        if not template:
                            raise HTTPException(422, "Лендинг больше недоступен")
                        content = {"description": template.description, "button_text": template.button_text, "badge_text": template.badge_text}
                    lander = await LanderAdminService(self.db).create_lander(project_id=project_id, actor=buyer, data=ProjectLanderCreate(
                        name=state["title"], type=template.type if template else "default_tg_redirect", slug=f"fb-{code}",
                        domain_id=None if state["domain"] == "tech" else UUID(state["domain"]),
                        auto_redirect_enabled=state.get("redirect", False), campaign=LanderTrackingCampaignCreate(**destination, ad_type="facebook"), **content,
                    ))
                    if template and template.type == "custom_upload":
                        await LanderService(self.db).copy_custom_assets(source_id=template.id, target_id=lander.id, project_id=project_id)
                else:
                    await TrackingService(self.db).create_tracking_link(actor=buyer, data=TrackingLinkCreate(project_id=project_id, **destination))
                await self.db.commit()
            await self.store.set(chat_id, {"project_id": str(project_id)})
            link = await self.db.scalar(select(TrackingLink).where(TrackingLink.code == code))
            await self.stats(chat_id, buyer, project_id, link_id=link.id)
        finally:
            if await lock.owned():
                await lock.release()

    async def message(self, chat_id, buyer, text):
        state = await self.store.get(chat_id) or {}
        if state.get("state") == "bw:search":
            state["state"] = None
            await self.store.set(chat_id, state)
            await self.links(chat_id, buyer, UUID(state["project_id"]), search=text[:100])
            return True
        if state.get("state") != "bw:name":
            return False
        if not text.strip() or len(text) > 100:
            await self.send(chat_id, "Название должно содержать от 1 до 100 символов")
            return True
        state.update(title=text.strip(), state="bw:mode")
        if state.get("facebook"):
            await self.pick(chat_id, buyer, state, "facebook")
        else:
            await self.choose(chat_id, state, "Тип ссылки:", [("Прямая", "direct"), ("Facebook с лендингом", "facebook")])
        return True

    async def callback(self, chat_id, buyer, data):
        if not data.startswith(("bw:", "quality:")):
            return False
        try:
            parts = data.split(":")
            state = await self.store.get(chat_id) or {}
            project_id = await self.owner._active_project_id(chat_id, buyer)
            if project_id is None:
                raise HTTPException(422, "Выберите проект")
            if parts[0] == "quality":
                link_id = UUID(parts[2])
                link = await TrafficQualityService(self.db).link(link_id, buyer)
                if parts[1] == "stats":
                    await self.stats(chat_id, buyer, link.project_id, link_id=link_id)
                else:
                    await TrafficQualityService(self.db).acknowledge(link_id, buyer, 1 if parts[1] == "snooze" else 24)
                    await self.send(chat_id, "Принято. Повторные уведомления временно отложены.")
            elif parts[1] in ("stats", "chart"):
                days = int(parts[2])
                if days not in (1, 7, 30):
                    raise ValueError()
                link_id = None if parts[3] == "project" else UUID(parts[3])
                if link_id:
                    link = await TrafficQualityService(self.db).link(link_id, buyer)
                    project_id = link.project_id
                await self.stats(chat_id, buyer, project_id, days, link_id, parts[1] == "chart")
            elif parts[1] in ("links", "clear"):
                await self.links(chat_id, buyer, project_id, max(0, int(parts[2])) if parts[1] == "links" else 0, state.get("link_search", "") if parts[1] == "links" else "")
            elif parts[1] == "alerts":
                await self.alerts(chat_id, buyer, project_id, max(0, int(parts[2])))
            elif parts[1] == "search":
                await self.store.set(chat_id, {"state": "bw:search", "project_id": str(project_id)})
                await self.send(chat_id, "Название или код ссылки:")
            elif parts[1] in ("pick", "page"):
                if state.get("nonce") != parts[2] or not str(state.get("state", "")).startswith("bw:"):
                    raise HTTPException(409, "Эта форма устарела")
                index = int(parts[3])
                if index < 0 or index >= len(state.get("options", [])):
                    raise ValueError()
                if parts[1] == "page":
                    await self.choose(chat_id, state, state["choice_title"], state["options"], index)
                else:
                    await self.pick(chat_id, buyer, state, state["options"][index][1])
            elif parts[1] == "confirm":
                await self.finish(chat_id, buyer, parts[2])
            elif parts[1] == "tags":
                link_id, offset = UUID(parts[2]), max(0, int(parts[3]))
                link = await TrafficQualityService(self.db).link(link_id, buyer)
                tags = (await self.db.scalars(select(Tag).where(Tag.project_id == link.project_id).order_by(Tag.name, Tag.id).offset(offset).limit(11))).all()
                state.update(tag_link=str(link_id), tag_options=[str(t.id) for t in tags[:10]])
                await self.store.set(chat_id, state)
                rows = [[(t.name, f"bw:tag:{index}")] for index, t in enumerate(tags[:10])]
                if len(tags) > 10:
                    rows.append([("Далее", f"bw:tags:{link_id}:{offset + 10}")])
                await self.send(chat_id, "Теги ссылки за 30 дней (по дате прихода лида):", rows)
            elif parts[1] == "tag":
                tag_id = UUID(state["tag_options"][int(parts[2])])
                link_id = UUID(state["tag_link"])
                link = await TrafficQualityService(self.db).link(link_id, buyer)
                today = date.today()
                stats = await TrackingMetricsService(self.db).get_tag_metrics(current_user=buyer, project_id=link.project_id, tag_id=tag_id, link_id=link_id, date_from=today - timedelta(days=29), date_to=today)
                photo = render_stats_chart(title=stats.tag_name, labels=[item.date.strftime("%d.%m") for item in stats.daily], leads=[item.count for item in stats.daily], submitted=[0 for _ in stats.daily], spend=[0 for _ in stats.daily], primary_label=stats.tag_name, secondary_label="")
                await self.db.commit()
                await self.telegram.send_photo(chat_id, photo, caption=f"{stats.tag_name}: {stats.total}. По дате прихода, как в CRM.")
        except (HTTPException, ValidationError, ValueError, KeyError, IndexError) as exc:
            await self.db.rollback()
            message = str(exc.detail) if isinstance(exc, HTTPException) else "Некорректные или устаревшие параметры. Откройте форму заново."
            await self.send(chat_id, message[:2000])
        return True
