"""Smoke active funnel Telegram runtime path.

This test is intentionally narrow: it creates a bot that still has a legacy
BotEngine scenario with the old fallback text, then publishes an active funnel
for the same bot. A simulated Telegram /start must send the funnel text, never
the old fallback.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.constants import MessageType, SenderType
from app.core.database import get_db_session
from app.models.bot import Bot, BotStep, BotVersion
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.message import Message
from app.models.project import Project
from app.models.role import Role
from app.models.user import User
from app.schemas.funnel import FunnelCreate, FunnelEdgeIn, FunnelGraphIn, FunnelStepIn
from app.schemas.telegram import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from app.services.funnel_service import FunnelService
from app.services.telegram_sender import TelegramSenderService
from app.services.telegram_service import TelegramService


OLD_FALLBACK_TEXT = "Привет! Я тестовый бот CRM. Напишите сообщение, и я сохраню ответ."

sent_messages: list[dict] = []


async def fake_send_message(
    self,
    project_id,
    bot_id,
    external_chat_id,
    text,
    reply_markup=None,
) -> None:
    sent_messages.append(
        {
            "project_id": str(project_id),
            "bot_id": str(bot_id) if bot_id else None,
            "external_chat_id": external_chat_id,
            "text": text,
            "reply_markup": reply_markup,
        }
    )


TelegramSenderService.send_message = fake_send_message


def now_id() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)


def update_text(external_chat_id: int, text: str) -> TelegramUpdate:
    message_id = now_id()
    return TelegramUpdate(
        update_id=message_id,
        message=TelegramMessage(
            message_id=message_id,
            text=text,
            chat=TelegramChat(id=external_chat_id),
            from_user=TelegramUser(
                id=external_chat_id,
                username="active_funnel_smoke",
                first_name="Active funnel smoke",
            ),
        ),
    )


async def get_or_create_role(db) -> Role:
    role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one_or_none()
    if role is not None:
        return role
    role = Role(name="admin")
    db.add(role)
    await db.flush()
    return role


async def create_project_bot_user(db) -> tuple[Project, Bot, User]:
    stamp = now_id()
    project = Project(
        name=f"Active funnel smoke {stamp}",
        slug=f"active-funnel-smoke-{stamp}",
        sla_threshold_minutes=30,
    )
    db.add(project)
    await db.flush()

    bot = Bot(
        project_id=project.id,
        name="Active funnel smoke bot",
        telegram_token="fake-token",
        bot_username="active_funnel_smoke_bot",
        telegram_bot_id=stamp,
        telegram_first_name="Active funnel smoke bot",
    )
    db.add(bot)
    await db.flush()

    role = await get_or_create_role(db)
    user = User(
        project_id=project.id,
        role_id=role.id,
        role=role,
        email=f"active-funnel-smoke-{stamp}@example.test",
        name="Active funnel smoke",
        password_hash="not-used",
    )
    db.add(user)
    await db.flush()
    return project, bot, user


async def create_legacy_fallback(db, bot: Bot) -> None:
    version = BotVersion(
        bot_id=bot.id,
        version_name="legacy fallback",
        is_active=True,
    )
    db.add(version)
    await db.flush()
    step = BotStep(
        bot_version_id=version.id,
        step_type="send_message",
        config={"text": OLD_FALLBACK_TEXT},
    )
    db.add(step)
    await db.flush()
    version.start_step_id = step.id
    await db.flush()


async def publish_start_message_funnel(
    db,
    project: Project,
    bot: Bot,
    user: User,
    text: str,
) -> None:
    service = FunnelService(db)
    funnel = await service.create_funnel(
        project_id=project.id,
        data=FunnelCreate(project_id=project.id, bot_id=bot.id, name=f"Start message {uuid4()}"),
        current_user=user,
    )
    assert funnel.draft_version_id is not None
    start_id = uuid4()
    message_id = uuid4()
    await service.save_graph(
        funnel_id=funnel.id,
        version_id=funnel.draft_version_id,
        project_id=project.id,
        graph=FunnelGraphIn(
            steps=[
                FunnelStepIn(
                    id=start_id,
                    key="start",
                    title="Старт",
                    step_type="trigger",
                    block_type="generic_trigger",
                    config_json={"trigger_type": "start_command"},
                ),
                FunnelStepIn(
                    id=message_id,
                    key="message",
                    title="Сообщение",
                    step_type="message",
                    block_type="generic_message",
                    config_json={"text": text},
                ),
            ],
            edges=[
                FunnelEdgeIn(
                    from_step_id=start_id,
                    to_step_id=message_id,
                )
            ],
        ),
        current_user=user,
    )
    await service.publish_version(
        funnel_id=funnel.id,
        version_id=funnel.draft_version_id,
        project_id=project.id,
        current_user=user,
    )


async def publish_start_input_message_funnel(
    db,
    project: Project,
    bot: Bot,
    user: User,
    prompt: str,
    final_text: str,
) -> None:
    service = FunnelService(db)
    funnel = await service.create_funnel(
        project_id=project.id,
        data=FunnelCreate(project_id=project.id, bot_id=bot.id, name=f"Start input {uuid4()}"),
        current_user=user,
    )
    assert funnel.draft_version_id is not None
    start_id = uuid4()
    input_id = uuid4()
    message_id = uuid4()
    await service.save_graph(
        funnel_id=funnel.id,
        version_id=funnel.draft_version_id,
        project_id=project.id,
        graph=FunnelGraphIn(
            steps=[
                FunnelStepIn(
                    id=start_id,
                    key="start",
                    title="Старт",
                    step_type="trigger",
                    block_type="generic_trigger",
                    config_json={"trigger_type": "start_command"},
                ),
                FunnelStepIn(
                    id=input_id,
                    key="input",
                    title="Вопрос",
                    step_type="input",
                    block_type="generic_input",
                    config_json={
                        "prompt": prompt,
                        "answer_type": "text",
                        "save_to": "name",
                    },
                ),
                FunnelStepIn(
                    id=message_id,
                    key="message",
                    title="Сообщение",
                    step_type="message",
                    block_type="generic_message",
                    config_json={"text": final_text},
                ),
            ],
            edges=[
                FunnelEdgeIn(from_step_id=start_id, to_step_id=input_id),
                FunnelEdgeIn(from_step_id=input_id, to_step_id=message_id),
            ],
        ),
        current_user=user,
    )
    await service.publish_version(
        funnel_id=funnel.id,
        version_id=funnel.draft_version_id,
        project_id=project.id,
        current_user=user,
    )


async def latest_message(db, chat_id, sender_type):
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id, Message.sender_type == sender_type)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def chat_by_external(db, project: Project, bot: Bot, external_chat_id: int) -> Chat:
    result = await db.execute(
        select(Chat).where(
            Chat.project_id == project.id,
            Chat.bot_id == bot.id,
            Chat.external_chat_id == str(external_chat_id),
            Chat.reset_at.is_(None),
        )
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise SystemExit("chat was not created")
    return chat


async def main() -> None:
    async with get_db_session() as db:
        project, bot, user = await create_project_bot_user(db)
        await create_legacy_fallback(db, bot)
        unique_text = f"SMOKE_ACTIVE_FUNNEL_MESSAGE_{now_id()}"
        await publish_start_message_funnel(db, project, bot, user, unique_text)
        await db.commit()
        await db.refresh(bot)

        external_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(external_chat_id, "/start"), bot.id)
        await db.commit()

        chat = await chat_by_external(db, project, bot, external_chat_id)
        incoming = await latest_message(db, chat.id, SenderType.USER)
        outgoing = await latest_message(db, chat.id, SenderType.BOT)
        if incoming is None or incoming.body != "/start":
            raise SystemExit("incoming /start was not stored")
        if outgoing is None:
            raise SystemExit("outgoing active funnel message was not stored")
        if outgoing.body == OLD_FALLBACK_TEXT:
            raise SystemExit("legacy fallback text was used instead of active funnel")
        if outgoing.body != unique_text:
            raise SystemExit(f"unexpected outgoing text: {outgoing.body!r}")
        if sent_messages[-1]["text"] != unique_text:
            raise SystemExit("Telegram sender did not receive active funnel text")

        state = (
            await db.execute(select(ChatFunnelState).where(ChatFunnelState.chat_id == chat.id))
        ).scalar_one_or_none()
        if state is None or state.funnel_version_id != bot.active_funnel_version_id:
            raise SystemExit("chat_funnel_state was not pinned to active version")

        prompt = f"SMOKE_INPUT_PROMPT_{now_id()}"
        final_text = f"SMOKE_INPUT_FINAL_{now_id()}"
        await publish_start_input_message_funnel(db, project, bot, user, prompt, final_text)
        await db.commit()
        await db.refresh(bot)

        input_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "/start"), bot.id)
        await db.commit()
        input_chat = await chat_by_external(db, project, bot, input_chat_id)
        question = await latest_message(db, input_chat.id, SenderType.BOT)
        if question is None or question.body != prompt:
            raise SystemExit("Start -> Input did not send prompt")

        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "Алиса"), bot.id)
        await db.commit()
        final = await latest_message(db, input_chat.id, SenderType.BOT)
        if final is None or final.body != final_text:
            raise SystemExit("Input answer did not advance to next active funnel message")
        if final.body == OLD_FALLBACK_TEXT:
            raise SystemExit("legacy fallback text was used after input answer")

    print("ok active_funnel_telegram_runtime")


if __name__ == "__main__":
    asyncio.run(main())
