from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.lander import ProjectDomain, ProjectLander
from app.models.tracking import TrackingLink
from app.services.utm_bridge_service import QueryParamInput, UtmBridgeService

logger = logging.getLogger(__name__)


class LanderNotFoundError(ValueError):
    pass


class LanderService:
    DEFAULT_TG_REDIRECT = "default_tg_redirect"
    CUSTOM_UPLOAD = "custom_upload"
    SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

    def __init__(
        self,
        db: AsyncSession,
        *,
        storage_root: str | Path = "static/landers",
        utm_bridge: UtmBridgeService | None = None,
    ) -> None:
        self.db = db
        self.storage_root = Path(storage_root)
        self.utm_bridge = utm_bridge or UtmBridgeService()

    async def save_custom_lander_zip(
        self,
        lander_id: UUID,
        zip_bytes: bytes,
        project_id: UUID,
    ) -> str:
        lander = await self._get_lander_for_project(lander_id, project_id)
        if lander.type != self.CUSTOM_UPLOAD:
            raise ValueError("ZIP-архив можно загрузить только для custom_upload лендинга")

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
        result = await self.db.execute(
            select(ProjectLander)
            .join(ProjectDomain, ProjectDomain.id == ProjectLander.domain_id)
            .options(
                selectinload(ProjectLander.domain),
                selectinload(ProjectLander.tracking_link).selectinload(TrackingLink.bot),
            )
            .where(
                ProjectDomain.domain_name == normalized_host,
                ProjectDomain.is_active.is_(True),
                ProjectLander.slug == normalized_slug,
                ProjectLander.is_active.is_(True),
            )
        )
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
    ) -> str:
        lander = await self.resolve_lander_request(host=host, slug=slug)
        telegram_url = await self.build_telegram_url(lander, query_params)

        if lander.type == self.DEFAULT_TG_REDIRECT:
            return self._render_default_redirect_html(lander, telegram_url)
        if lander.type == self.CUSTOM_UPLOAD:
            html_body = await self._read_custom_index_html(lander)
            return self.replace_bot_links(html_body, telegram_url, lander)

        raise ValueError("Недопустимый тип лендинга")

    async def build_telegram_url(
        self,
        lander: ProjectLander,
        query_params: QueryParamInput | None = None,
    ) -> str:
        tracking_link = lander.tracking_link
        if tracking_link is None:
            raise ValueError("Лендинг должен быть привязан к tracking link")

        username = self._bot_username(lander)
        if not username:
            raise ValueError("CLIENT_BOT_USERNAME не настроен")

        code = (tracking_link.code or tracking_link.ref_code or "").strip()
        if not code:
            raise ValueError("Tracking link не содержит code")

        utm_key = await self.utm_bridge.store_query_params(query_params)
        start_payload = quote(f"ref_{code}_{utm_key}", safe="")
        return f"https://t.me/{username}?start={start_payload}"

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
        updated = html_body
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
        if not lander.custom_html_path:
            raise ValueError("Для кастомного лендинга не загружен HTML")

        root = self.storage_root.resolve()
        directory = Path(lander.custom_html_path)
        if not directory.is_absolute():
            directory = directory.resolve()
        try:
            directory.relative_to(root)
        except ValueError as exc:
            raise ValueError("Некорректный путь к кастомному лендингу") from exc

        index_path = directory / "index.html"
        if not index_path.is_file():
            raise ValueError("В директории лендинга отсутствует index.html")
        return await asyncio.to_thread(index_path.read_text, encoding="utf-8")

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

    @staticmethod
    def _render_default_redirect_html(
        lander: ProjectLander,
        telegram_url: str,
    ) -> str:
        title = html.escape(lander.name or "Telegram", quote=True)
        safe_url = html.escape(telegram_url, quote=True)
        return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #05070c;
      --panel: rgba(12, 18, 30, .82);
      --line: rgba(52, 211, 153, .28);
      --text: #f4f7fb;
      --muted: #9aa4b2;
      --accent: #34d399;
      --accent-2: #22d3ee;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      background:
        radial-gradient(circle at 50% 0%, rgba(34, 211, 238, .18), transparent 34rem),
        linear-gradient(135deg, #05070c 0%, #111827 52%, #06130f 100%);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(100%, 440px);
      padding: 32px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--panel);
      box-shadow: 0 24px 80px rgba(16, 185, 129, .14), inset 0 1px 0 rgba(255, 255, 255, .06);
      backdrop-filter: blur(18px);
      text-align: center;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 28px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(34, 211, 238, .32);
      color: #a5f3fc;
      background: rgba(34, 211, 238, .08);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 18px 0 10px;
      font-size: clamp(30px, 8vw, 44px);
      line-height: 1;
      letter-spacing: 0;
    }}
    p {{
      margin: 0 auto 28px;
      max-width: 30rem;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.55;
    }}
    a {{
      display: inline-flex;
      min-height: 52px;
      width: 100%;
      align-items: center;
      justify-content: center;
      border-radius: 16px;
      color: #02130d;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      box-shadow: 0 0 34px rgba(52, 211, 153, .28);
      text-decoration: none;
      font-weight: 800;
      transition: transform .18s ease, box-shadow .18s ease;
    }}
    a:hover {{
      transform: translateY(-1px);
      box-shadow: 0 0 48px rgba(52, 211, 153, .38);
    }}
  </style>
</head>
<body>
  <main>
    <div class="badge">Telegram доступ</div>
    <h1>{title}</h1>
    <p>Нажмите кнопку ниже, чтобы открыть Telegram и продолжить в защищенном чате.</p>
    <a href="{safe_url}" rel="noopener noreferrer">Открыть Telegram</a>
  </main>
</body>
</html>"""
