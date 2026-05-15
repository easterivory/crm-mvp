"""
Idempotently seed a Telegram test bot and a minimal welcome scenario.

Usage:
    TELEGRAM_BOT_TOKEN=... python scripts/seed_test_bot.py

Optional:
    TELEGRAM_PROJECT_ID=<existing project uuid>
    TEST_BOT_PROJECT_NAME="Test Telegram Project"
    TEST_BOT_NAME="CRM Test Bot"
"""
import asyncio
import os
import re
import sys
import unicodedata
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import get_db_session
from app.models.bot import Bot, BotStep, BotVersion
from app.models.project import Project


DEFAULT_PROJECT_NAME = "Test CRM Project"
DEFAULT_BOT_NAME = "CRM Test Bot"
DEFAULT_VERSION_NAME = "v1.0"
DEFAULT_WELCOME_TEXT = "Привет! Я тестовый бот CRM. Напишите сообщение, и я сохраню ответ."


def _slugify_project_name(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "project"


async def _get_or_create_project(db) -> Project:
    project_id = os.getenv("TELEGRAM_PROJECT_ID") or settings.TELEGRAM_PROJECT_ID
    project_name = (
        os.getenv("TEST_BOT_PROJECT_NAME")
        or os.getenv("TEST_PROJECT_NAME")
        or DEFAULT_PROJECT_NAME
    )
    if project_id:
        project = await db.get(Project, UUID(project_id))
        if project is not None and project.is_deleted:
            raise RuntimeError(f"Project is deleted: {project_id}")
        if project is not None:
            return project

        project = Project(
            id=UUID(project_id),
            name=project_name,
            slug=_slugify_project_name(project_name),
            sla_threshold_minutes=30,
        )
        db.add(project)
        await db.flush()
        await db.refresh(project)
        return project

    result = await db.execute(
        select(Project).where(Project.name == project_name, Project.is_deleted.is_(False))
    )
    project = result.scalar_one_or_none()
    if project is not None:
        return project

    project = Project(
        name=project_name,
        slug=_slugify_project_name(project_name),
        sla_threshold_minutes=30,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _get_or_create_bot(db, project: Project, token: str) -> Bot:
    bot_name = os.getenv("TEST_BOT_NAME", DEFAULT_BOT_NAME)
    result = await db.execute(
        select(Bot).where(
            Bot.project_id == project.id,
            Bot.name == bot_name,
            Bot.is_deleted.is_(False),
        )
    )
    bot = result.scalar_one_or_none()
    if bot is None:
        bot = Bot(project_id=project.id, name=bot_name, telegram_token=token)
        db.add(bot)
        await db.flush()
        await db.refresh(bot)
    else:
        bot.telegram_token = token
    return bot


async def _get_or_create_version(db, bot: Bot) -> BotVersion:
    result = await db.execute(
        select(BotVersion).where(BotVersion.bot_id == bot.id, BotVersion.is_active.is_(True))
    )
    version = result.scalar_one_or_none()
    if version is not None:
        return version

    version = BotVersion(
        bot_id=bot.id,
        version_name=DEFAULT_VERSION_NAME,
        is_active=True,
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


async def _ensure_welcome_step(db, version: BotVersion) -> BotStep:
    if version.start_step_id is not None:
        step = await db.get(BotStep, version.start_step_id)
        if step is not None:
            return step

    step = BotStep(
        bot_version_id=version.id,
        step_type="send_message",
        config={"text": DEFAULT_WELCOME_TEXT},
        next_step_id=None,
        fallback_step_id=None,
    )
    db.add(step)
    await db.flush()
    await db.refresh(step)

    version.start_step_id = step.id
    await db.flush()
    return step


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    async with get_db_session() as db:
        try:
            project = await _get_or_create_project(db)
            bot = await _get_or_create_bot(db, project, token)
            version = await _get_or_create_version(db, bot)
            step = await _ensure_welcome_step(db, version)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    print("Seeded test bot")
    print(f"project_id={project.id}")
    print(f"bot_id={bot.id}")
    print(f"bot_version_id={version.id}")
    print(f"start_step_id={step.id}")
    print("Set TELEGRAM_PROJECT_ID to the project_id above before webhook testing.")


if __name__ == "__main__":
    asyncio.run(main())
