from __future__ import annotations

import asyncio
import html
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from collections.abc import Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.facebook_events import normalize_facebook_event_mappings
from app.core.lander_urls import effective_campaign_utm_defaults
from app.core.telegram_links import build_telegram_bot_start_link
from app.models.lander import ProjectDomain, ProjectLander
from app.models.tracking import TrackingLink
from app.repositories.tracking_repository import TrackingEventRepository
from app.services.utm_bridge_service import QueryParamInput, UtmBridgeService

logger = logging.getLogger(__name__)


class LanderNotFoundError(ValueError):
    pass


class LanderService:
    DEFAULT_TG_REDIRECT = "default_tg_redirect"
    CUSTOM_UPLOAD = "custom_upload"
    SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
    CUSTOM_TELEGRAM_LINK_RE = re.compile(
        r"(?P<open><a\b(?=[^>]*\bdata-crm-telegram-link(?=\s|=|/|>))[^>]*)(?P<close>>)",
        re.IGNORECASE,
    )
    HREF_ATTRIBUTE_RE = re.compile(
        r"(?P<prefix>\bhref\s*=\s*)(?P<quote>[\"'])(?P<url>[^\"']*)(?P=quote)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        db: AsyncSession,
        *,
        storage_root: str | Path | None = None,
        utm_bridge: UtmBridgeService | None = None,
    ) -> None:
        self.db = db
        self.storage_root = Path(storage_root or settings.LANDER_STORAGE_PATH)
        self.utm_bridge = utm_bridge or UtmBridgeService()
        self.tracking_event_repo = TrackingEventRepository(db)

    async def save_custom_lander_zip(
        self,
        lander_id: UUID,
        zip_bytes: bytes,
        project_id: UUID,
    ) -> str:
        lander = await self._get_lander_for_project(lander_id, project_id)

        slug = self._safe_slug(lander.slug)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_zip_path = tempfile.mkstemp(prefix=f"{slug}_", suffix=".zip")
        os.close(temp_fd)
        destination = self.storage_root / slug

        try:
            await asyncio.to_thread(Path(temp_zip_path).write_bytes, zip_bytes)
            await asyncio.to_thread(
                self._extract_zip_to_destination,
                Path(temp_zip_path),
                destination,
                slug,
            )
        finally:
            Path(temp_zip_path).unlink(missing_ok=True)

        lander.custom_html_path = destination.as_posix()
        await self.db.flush()
        await self.db.refresh(lander)
        return lander.custom_html_path

    async def resolve_lander_request(self, host: str, slug: str) -> ProjectLander:
        normalized_host = self.normalize_host(host)
        normalized_slug = self._safe_slug(slug)
        stmt = select(ProjectLander).options(
            selectinload(ProjectLander.domain),
            selectinload(ProjectLander.tracking_link).selectinload(TrackingLink.bot),
        )
        technical_domain = self.normalize_host(settings.LANDER_TECH_DOMAIN)
        if technical_domain and normalized_host == technical_domain:
            stmt = stmt.where(
                ProjectLander.slug == normalized_slug,
                ProjectLander.is_active.is_(True),
            )
        else:
            stmt = stmt.join(
                ProjectDomain,
                ProjectDomain.id == ProjectLander.domain_id,
            ).where(
                ProjectDomain.domain_name == normalized_host,
                ProjectDomain.is_active.is_(True),
                ProjectLander.slug == normalized_slug,
                ProjectLander.is_active.is_(True),
            )
        result = await self.db.execute(stmt)
        lander = result.scalar_one_or_none()
        if lander is None:
            raise LanderNotFoundError("Лендинг не найден")
        return lander

    async def render_lander_html(
        self,
        *,
        host: str,
        slug: str,
        query_params: QueryParamInput | None = None,
        browser_context: Mapping[str, object] | None = None,
    ) -> str:
        lander = await self.resolve_lander_request(host=host, slug=slug)
        browser_event_seed = uuid4().hex
        enriched_browser_context = dict(browser_context or {})
        enriched_browser_context["lander_event_seed"] = browser_event_seed
        telegram_url, start_key = await self.build_telegram_bridge(
            lander,
            query_params,
            browser_context=enriched_browser_context,
        )
        pixel_markup = self._render_pixel_markup(
            lander.pixels_json,
            lander.meta_events_json,
            tracking_link=lander.tracking_link,
            browser_event_seed=browser_event_seed,
            bridge_url=f"/l/{lander.slug}/bridge/{start_key}",
        )

        if lander.type == self.DEFAULT_TG_REDIRECT:
            rendered_html = self._render_default_redirect_html(
                lander,
                telegram_url,
                pixel_markup,
            )
        elif lander.type == self.CUSTOM_UPLOAD:
            html_body = await self._read_custom_index_html(lander)
            html_body = self._inject_base_href(html_body, f"/l/{lander.slug}/")
            html_body = self._inject_head_markup(html_body, pixel_markup)
            rendered_html = self.replace_bot_links(html_body, telegram_url, lander)
        else:
            raise ValueError("Недопустимый тип лендинга")

        await self._record_lander_click(lander)
        return rendered_html

    async def _record_lander_click(self, lander: ProjectLander) -> None:
        tracking_link = lander.tracking_link
        if tracking_link is None:
            return
        try:
            async with self.db.begin_nested():
                await self.tracking_event_repo.increment_lander_click(
                    project_id=lander.project_id,
                    tracking_link_id=tracking_link.id,
                )
        except Exception:
            logger.exception(
                "Could not record lander click lander_id=%s tracking_link_id=%s",
                lander.id,
                tracking_link.id,
            )

    async def resolve_custom_asset(
        self,
        *,
        host: str,
        slug: str,
        asset_path: str,
    ) -> tuple[Path, str]:
        lander = await self.resolve_lander_request(host=host, slug=slug)
        if lander.type != self.CUSTOM_UPLOAD:
            raise LanderNotFoundError("Ассет доступен только для custom_upload лендинга")

        directory = await self._custom_lander_directory(lander)
        member_path = self._safe_member_path(asset_path)
        file_path = (directory / member_path).resolve()
        try:
            file_path.relative_to(directory.resolve())
        except ValueError as exc:
            raise ValueError("Некорректный путь к ассету лендинга") from exc
        if not file_path.is_file():
            raise LanderNotFoundError("Ассет лендинга не найден")
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return file_path, media_type

    async def build_telegram_url(
        self,
        lander: ProjectLander,
        query_params: QueryParamInput | None = None,
        *,
        browser_context: Mapping[str, object] | None = None,
    ) -> str:
        telegram_url, _ = await self.build_telegram_bridge(
            lander,
            query_params,
            browser_context=browser_context,
        )
        return telegram_url

    async def build_telegram_bridge(
        self,
        lander: ProjectLander,
        query_params: QueryParamInput | None = None,
        *,
        browser_context: Mapping[str, object] | None = None,
    ) -> tuple[str, str]:
        tracking_link = lander.tracking_link
        if tracking_link is None:
            raise ValueError("Лендинг должен быть привязан к tracking link")

        username = self._bot_username(lander)
        if not username:
            raise ValueError("CLIENT_BOT_USERNAME не настроен")

        code = (tracking_link.code or tracking_link.ref_code or "").strip()
        if not code:
            raise ValueError("Tracking link не содержит code")

        utm_params = effective_campaign_utm_defaults(
            lander.utm_defaults_json,
            tracking_code=code,
            is_facebook_campaign=tracking_link.fb_campaign_enabled,
        )
        utm_params.update(self.utm_bridge.normalize_query_params(query_params))
        start_key = await self.utm_bridge.store_lander_start(
            ref_code=code,
            query_params=utm_params,
            browser_context=browser_context,
        )
        start_payload = self.utm_bridge.build_lander_start_payload(
            tracking_link.id,
            start_key,
        )
        return build_telegram_bot_start_link(username, start_payload), start_key

    def replace_bot_links(
        self,
        html_body: str,
        telegram_url: str,
        lander: ProjectLander,
    ) -> str:
        usernames = {
            item
            for item in (
                self._bot_username(lander),
                (settings.CLIENT_BOT_USERNAME or "").removeprefix("@").strip(),
            )
            if item
        }
        escaped_url = html.escape(telegram_url, quote=True)
        def replace_marked_link(match: re.Match[str]) -> str:
            opening_tag = match.group("open")
            href_match = self.HREF_ATTRIBUTE_RE.search(opening_tag)
            if href_match is None:
                opening_tag = f'{opening_tag} href="{escaped_url}"'
            else:
                opening_tag = self.HREF_ATTRIBUTE_RE.sub(
                    lambda href: (
                        f"{href.group('prefix')}{href.group('quote')}"
                        f"{escaped_url}{href.group('quote')}"
                    ),
                    opening_tag,
                    count=1,
                )
            return f"{opening_tag}{match.group('close')}"

        updated = self.CUSTOM_TELEGRAM_LINK_RE.sub(replace_marked_link, html_body)
        for username in usernames:
            username_re = re.escape(username)
            href_re = re.compile(
                rf"(?P<prefix>\bhref\s*=\s*)(?P<quote>[\"'])"
                rf"(?P<url>[^\"']*(?:t\.me|telegram\.me)/{username_re}[^\"']*)"
                rf"(?P=quote)",
                re.IGNORECASE,
            )
            updated = href_re.sub(
                lambda match: (
                    f"{match.group('prefix')}{match.group('quote')}"
                    f"{escaped_url}{match.group('quote')}"
                ),
                updated,
            )
        return updated

    async def _get_lander_for_project(self, lander_id: UUID, project_id: UUID) -> ProjectLander:
        result = await self.db.execute(
            select(ProjectLander).where(
                ProjectLander.id == lander_id,
                ProjectLander.project_id == project_id,
            )
        )
        lander = result.scalar_one_or_none()
        if lander is None:
            raise LanderNotFoundError("Лендинг не найден")
        return lander

    async def _read_custom_index_html(self, lander: ProjectLander) -> str:
        directory = await self._custom_lander_directory(lander)
        index_path = directory / "index.html"
        if not index_path.is_file():
            raise ValueError("В директории лендинга отсутствует index.html")
        return await asyncio.to_thread(index_path.read_text, encoding="utf-8")

    async def _custom_lander_directory(self, lander: ProjectLander) -> Path:
        if not lander.custom_html_path:
            raise ValueError("Для кастомного лендинга не загружен HTML")

        roots = [self.storage_root.resolve()]
        legacy_root = Path("static/landers").resolve()
        if legacy_root not in roots:
            roots.append(legacy_root)
        directory = Path(lander.custom_html_path)
        if not directory.is_absolute():
            directory = directory.resolve()
        for root in roots:
            try:
                directory.relative_to(root)
                return directory
            except ValueError:
                continue
        raise ValueError("Некорректный путь к кастомному лендингу")

    @staticmethod
    def _inject_base_href(html_body: str, base_href: str) -> str:
        if re.search(r"<base\b", html_body, flags=re.IGNORECASE):
            return html_body
        safe_href = html.escape(base_href, quote=True)
        head_match = re.search(r"<head\b[^>]*>", html_body, flags=re.IGNORECASE)
        if head_match is None:
            return f'<base href="{safe_href}">\n{html_body}'
        insert_at = head_match.end()
        return f'{html_body[:insert_at]}\n  <base href="{safe_href}">{html_body[insert_at:]}'

    @staticmethod
    def _inject_head_markup(html_body: str, markup: str) -> str:
        if not markup:
            return html_body
        closing_head = re.search(r"</head\\s*>", html_body, flags=re.IGNORECASE)
        if closing_head is not None:
            return f"{html_body[:closing_head.start()]}\n{markup}\n{html_body[closing_head.start():]}"
        return f"{markup}\n{html_body}"

    @classmethod
    def _extract_zip_to_destination(
        cls,
        zip_path: Path,
        destination: Path,
        slug: str,
    ) -> None:
        cls._safe_slug(slug)
        destination_parent = destination.parent
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{slug}_", dir=destination_parent))
        try:
            with zipfile.ZipFile(zip_path) as archive:
                members = archive.infolist()
                cls._validate_zip_members(members)
                for member in members:
                    if member.is_dir():
                        (temp_dir / cls._safe_member_path(member.filename)).mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        continue
                    member_path = cls._safe_member_path(member.filename)
                    target_path = temp_dir / member_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target_path.open("wb") as target:
                        shutil.copyfileobj(source, target)

            cls._validate_custom_index_contract(temp_dir / "index.html")
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(temp_dir.as_posix(), destination.as_posix())
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    @classmethod
    def _validate_zip_members(cls, members: list[zipfile.ZipInfo]) -> None:
        has_top_level_index = False
        for member in members:
            member_path = cls._safe_member_path(member.filename)
            if member_path == PurePosixPath("index.html") and not member.is_dir():
                has_top_level_index = True
            if cls._is_zip_symlink(member):
                raise ValueError("Попытка уязвимости: недопустимые пути в архиве")
        if not has_top_level_index:
            raise ValueError("В архиве должен быть файл index.html")

    @classmethod
    def _validate_custom_index_contract(cls, index_path: Path) -> None:
        try:
            index_html = index_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("index.html должен быть в UTF-8") from exc
        if not cls.CUSTOM_TELEGRAM_LINK_RE.search(index_html):
            raise ValueError(
                "В index.html нужна Telegram-кнопка: "
                '<a data-crm-telegram-link href="#">Открыть Telegram</a>'
            )

    @staticmethod
    def _safe_member_path(filename: str) -> PurePosixPath:
        normalized = filename.replace("\\", "/")
        if (
            normalized.startswith("/")
            or normalized.startswith("\\")
            or PurePosixPath(normalized).is_absolute()
            or PureWindowsPath(filename).is_absolute()
        ):
            raise ValueError("Попытка уязвимости: недопустимые пути в архиве")

        member_path = PurePosixPath(normalized)
        if ".." in member_path.parts:
            raise ValueError("Попытка уязвимости: недопустимые пути в архиве")
        if not member_path.parts:
            raise ValueError("Попытка уязвимости: недопустимые пути в архиве")
        return member_path

    @staticmethod
    def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
        mode = member.external_attr >> 16
        return (mode & 0o170000) == 0o120000

    @classmethod
    def _safe_slug(cls, slug: str) -> str:
        normalized = (slug or "").strip()
        if not cls.SAFE_SLUG_RE.fullmatch(normalized):
            raise ValueError("Invalid lander slug")
        return normalized

    @staticmethod
    def normalize_host(host: str) -> str:
        normalized = (host or "").strip().lower().split(",", maxsplit=1)[0]
        if normalized.startswith("[") and "]" in normalized:
            return normalized[1 : normalized.index("]")].rstrip(".")
        return normalized.split(":", maxsplit=1)[0].rstrip(".")

    @staticmethod
    def _bot_username(lander: ProjectLander) -> str:
        tracking_link = lander.tracking_link
        bot_username = ""
        if tracking_link is not None and tracking_link.bot is not None:
            bot_username = tracking_link.bot.bot_username or ""
        return (bot_username or settings.CLIENT_BOT_USERNAME or "").removeprefix("@").strip()

    @classmethod
    def _render_pixel_markup(
        cls,
        pixels: object,
        meta_events: object = None,
        *,
        tracking_link: TrackingLink | None = None,
        browser_event_seed: str | None = None,
        bridge_url: str | None = None,
    ) -> str:
        meta_pixel_id: str | None = None
        campaign_mappings: list[dict] = []
        if tracking_link is not None and tracking_link.fb_campaign_enabled:
            candidate = str(tracking_link.fb_pixel_id or "").strip()
            if cls._is_safe_pixel_id(candidate):
                meta_pixel_id = candidate
            try:
                campaign_mappings = normalize_facebook_event_mappings(
                    tracking_link.fb_event_mappings_json
                )
            except ValueError:
                logger.warning(
                    "Invalid Facebook event mapping on tracking_link_id=%s; using legacy lander events",
                    tracking_link.id,
                )

        if meta_pixel_id is None and isinstance(pixels, list):
            for raw_pixel in pixels:
                if not isinstance(raw_pixel, dict):
                    continue
                provider = str(raw_pixel.get("provider") or "").strip()
                pixel_id = str(raw_pixel.get("pixel_id") or "").strip()
                if not cls._is_safe_pixel_id(pixel_id):
                    logger.warning("Skipped invalid landing pixel provider=%s", provider)
                    continue
                if provider == "meta" and meta_pixel_id is None:
                    meta_pixel_id = pixel_id

        if meta_pixel_id is None:
            return ""

        pixel_json = json.dumps(meta_pixel_id).replace("<", "\\u003c")
        pixel_attr = html.escape(meta_pixel_id, quote=True)
        return (
            "<script>!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?"
            "n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;"
            "n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];"
            "s.parentNode.insertBefore(t,s)}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');"
            f"fbq('init',{pixel_json});</script>"
            f"<noscript><img height=\"1\" width=\"1\" style=\"display:none\" src=\"https://www.facebook.com/tr?id={pixel_attr}&ev=PageView&noscript=1\" alt=\"\"></noscript>"
            f"{cls._render_meta_event_bridge(meta_events, campaign_mappings, browser_event_seed, bridge_url)}"
        )

    @staticmethod
    def _render_meta_event_bridge(
        meta_events: object,
        event_mappings: list[dict] | None = None,
        browser_event_seed: str | None = None,
        bridge_url: str | None = None,
    ) -> str:
        event_names: list[str] = []
        if isinstance(meta_events, list):
            for raw_event in meta_events:
                raw_name = raw_event.get("name") if isinstance(raw_event, dict) else raw_event
                name = str(raw_name or "").strip()
                if (
                    len(name) <= 40
                    and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name)
                    and name not in event_names
                ):
                    event_names.append(name)
        event_names_json = json.dumps(event_names).replace("<", "\\u003c")
        mappings_by_source = {
            str(mapping["source_event"]): mapping
            for mapping in (event_mappings or [])
            if mapping.get("enabled")
        }
        mappings_json = json.dumps(
            mappings_by_source,
            ensure_ascii=True,
            separators=(",", ":"),
        ).replace("<", "\\u003c")
        event_seed_json = json.dumps(browser_event_seed or uuid4().hex).replace(
            "<", "\\u003c"
        )
        bridge_url_json = json.dumps(bridge_url or "").replace("<", "\\u003c")
        return (
            "<script>"
            f"var crmFacebookMappings={mappings_json};var crmFacebookSeed={event_seed_json};"
            f"var crmFacebookBridgeUrl={bridge_url_json};"
            "var crmFacebookEventSequence=0;"
            "var crmMetaStandardEvents={pageview:'PageView',viewcontent:'ViewContent',search:'Search',"
            "addtocart:'AddToCart',addtowishlist:'AddToWishlist',initiatecheckout:'InitiateCheckout',"
            "addpaymentinfo:'AddPaymentInfo',purchase:'Purchase',lead:'Lead',"
            "completeregistration:'CompleteRegistration',contact:'Contact',"
            "customizeproduct:'CustomizeProduct',donate:'Donate',findlocation:'FindLocation',"
            "schedule:'Schedule',starttrial:'StartTrial',submitapplication:'SubmitApplication',"
            "subscribe:'Subscribe'};"
            "var crmMetaAliases={registration:'CompleteRegistration',reg:'CompleteRegistration',"
            "complete_registration:'CompleteRegistration',application:'SubmitApplication'};"
            "function crmFacebookEventId(source){crmFacebookEventSequence+=1;"
            "return 'crm_'+crmFacebookSeed+'_'+String(source||'event')+'_'+crmFacebookEventSequence;}"
            "function crmFacebookParams(raw){var result={};if(!raw||typeof raw!=='object'){return result;}"
            "Object.keys(raw).forEach(function(key){var value=raw[key];"
            "if(value===null||value===undefined||/\\{\\{[^}]+\\}\\}/.test(String(value))){return;}"
            "result[key]=value;});return result;}"
            "function crmFacebookDispatch(rawName,params,eventId){"
            "var raw=String(rawName||'').trim();"
            "if(!/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(raw)){return;}"
            "var normalized=crmMetaAliases[raw.toLowerCase()]||crmMetaStandardEvents[raw.toLowerCase()]||raw;"
            "if(!window.fbq){return;}"
            "var method=crmMetaStandardEvents[normalized.toLowerCase()]?'track':'trackCustom';"
            "window.fbq(method,normalized,crmFacebookParams(params),{eventID:eventId||crmFacebookEventId(normalized)});};"
            "window.__crmTrackMetaEvent=window.__crmTrackMetaEvent||function(rawName,params){"
            "crmFacebookDispatch(rawName,params,crmFacebookEventId(rawName));};"
            "window.__crmTrackFacebookSource=window.__crmTrackFacebookSource||function(source,overrides){"
            "var key=String(source||'').trim().toLowerCase();var mapping=crmFacebookMappings[key];"
            "if(!mapping||mapping.enabled===false){return;}var params=Object.assign({},mapping.parameters||{},overrides||{});"
            "crmFacebookDispatch(mapping.event_name,params,crmFacebookEventId(key));};"
            "window.__crmSyncFacebookContext=window.__crmSyncFacebookContext||(function(){"
            "var pending=null;return function(){"
            "if(!crmFacebookBridgeUrl||!window.fetch){return Promise.resolve();}"
            "if(pending){return pending;}"
            "var cookies={};String(document.cookie||'').split(';').forEach(function(item){"
            "var parts=item.split('=');var key=String(parts.shift()||'').trim();"
            "if(key==='_fbp'||key==='_fbc'){cookies[key]=decodeURIComponent(parts.join('=')||'');}});"
            "cookies.event_source_url=window.location.href;"
            "pending=fetch(crmFacebookBridgeUrl,{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify(cookies),credentials:'same-origin',keepalive:true})"
            ".catch(function(){}).finally(function(){pending=null;});return pending;};}());"
            "if(crmFacebookMappings.page_view&&crmFacebookMappings.page_view.enabled!==false){"
            "if(String(crmFacebookMappings.page_view.event_name).toLowerCase()!=='pageview'){"
            "crmFacebookDispatch('PageView',{},crmFacebookEventId('base_page_view'));}"
            "window.__crmTrackFacebookSource('page_view');"
            "}else{crmFacebookDispatch('PageView',{},crmFacebookEventId('page_view'));}"
            "window.__crmTrackTelegramOpen=window.__crmTrackTelegramOpen||(function(){"
            "var tracked=false;return function(){if(tracked){return;}tracked=true;"
            "if(crmFacebookMappings.telegram_click&&crmFacebookMappings.telegram_click.enabled!==false){"
            "window.__crmTrackFacebookSource('telegram_click',{content_name:'Telegram',content_category:'landing'});"
            "}else if(window.fbq){crmFacebookDispatch('Lead',{content_name:'Telegram',content_category:'landing'},crmFacebookEventId('telegram_click'));"
            "crmFacebookDispatch('TelegramOpen',{},crmFacebookEventId('telegram_open'));}"
            f"var extraEvents={event_names_json};for(var index=0;index<extraEvents.length;index+=1){{window.__crmTrackMetaEvent(extraEvents[index]);}}"
            "};}());"
            "document.addEventListener('click',function(event){var target=event.target;"
            "var sourceTarget=target&&target.closest?target.closest('[data-crm-fb-source]'):null;"
            "if(sourceTarget){window.__crmTrackFacebookSource(sourceTarget.getAttribute('data-crm-fb-source'));}"
            "var eventTarget=target&&target.closest?target.closest('[data-crm-meta-event]'):null;"
            "if(eventTarget){window.__crmTrackMetaEvent(eventTarget.getAttribute('data-crm-meta-event'));}"
            "var link=target&&target.closest?target.closest('a[data-crm-telegram-link]'):null;"
            "if(!link){return;}window.__crmTrackTelegramOpen();window.__crmSyncFacebookContext();"
            "if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.target){return;}"
            "event.preventDefault();window.setTimeout(function(){window.location.assign(link.href);},80);});"
            "document.addEventListener('submit',function(event){var form=event.target;"
            "if(form&&form.getAttribute){var source=form.getAttribute('data-crm-fb-source');"
            "if(source){window.__crmTrackFacebookSource(source);}"
            "window.__crmTrackMetaEvent(form.getAttribute('data-crm-meta-event'));}});"
            "</script>"
        )

    @staticmethod
    def _is_safe_pixel_id(value: str) -> bool:
        return bool(value) and len(value) <= 120 and all(
            char.isascii() and (char.isalnum() or char in "._-") for char in value
        )

    @staticmethod
    def _render_default_redirect_html(
        lander: ProjectLander,
        telegram_url: str,
        pixel_markup: str,
    ) -> str:
        safe_url = html.escape(telegram_url, quote=True)
        safe_url_json = json.dumps(telegram_url).replace("<", "\\u003c")
        auto_redirect_script = "window.setTimeout(openTelegram, 650);" if lander.auto_redirect_enabled else ""
        return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telegram</title>
  {pixel_markup}
  <style>
    :root {{
      color-scheme: light;
      --telegram-blue: #3390ec;
      --telegram-blue-hover: #2782dc;
      --text: #1f2937;
      --muted: #6b7280;
      --line: #e7edf3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: 24px 18px;
      background: #ffffff;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    main {{
      width: min(100%, 440px);
      padding: 16px 8px 28px;
      text-align: center;
    }}
    .logo {{
      width: 104px;
      height: 104px;
      margin: 0 auto 24px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 26px;
      line-height: 1.25;
      font-weight: 600;
    }}
    p {{
      margin: 0 auto 24px;
      max-width: 22rem;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.45;
    }}
    a {{
      display: inline-flex;
      min-height: 50px;
      width: 100%;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      color: #ffffff;
      background: var(--telegram-blue);
      text-decoration: none;
      font-size: 16px;
      font-weight: 600;
      transition: background .18s ease;
    }}
    a:hover {{
      background: var(--telegram-blue-hover);
    }}
    .hint {{
      margin-top: 16px;
      color: #9ca3af;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <main>
    <img class="logo" src="https://telegram.org/img/t_logo.png" alt="Telegram">
    <h1>Open Telegram</h1>
    <a id="open-telegram" data-crm-telegram-link href="{safe_url}" rel="noopener noreferrer">Open in Telegram</a>
    <div class="hint">Tap the button to continue.</div>
  </main>
  <script>
    (function () {{
      var target = {safe_url_json};
      var opened = false;
      function openTelegram() {{
        if (opened) return;
        opened = true;
        if (window.__crmTrackTelegramOpen) window.__crmTrackTelegramOpen();
        var sync = window.__crmSyncFacebookContext ? window.__crmSyncFacebookContext() : Promise.resolve();
        Promise.race([sync, new Promise(function (resolve) {{ window.setTimeout(resolve, 180); }})])
          .finally(function () {{ window.location.href = target; }});
      }}
      document.getElementById('open-telegram').addEventListener('click', function (event) {{
        event.preventDefault();
        window.setTimeout(openTelegram, 80);
      }});
      {auto_redirect_script}
    }}());
  </script>
</body>
</html>"""
