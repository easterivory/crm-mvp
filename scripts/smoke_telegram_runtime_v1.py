"""Smoke Telegram runtime v1 without calling the real Telegram API.

Checks:
  - active published funnel drives /start
  - Start -> Message sends configured text and stores outgoing CRM message
  - Start -> Input -> Message waits, maps answer to lead, then continues
  - media messages store Telegram metadata instead of "[file]"
  - media proxy is lazy: getFile is called, file bytes are not downloaded until streamed
  - chat reset lets the next /start begin the active funnel again
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
from app.models.bot import Bot
from app.models.funnel import Funnel, FunnelEdge, FunnelStep, FunnelVersion
from app.models.message import Message
from app.models.project import Project
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.telegram import TelegramChat, TelegramFile, TelegramMessage, TelegramUpdate, TelegramUser
from app.services.chat_service import ChatService
from app.services.message_service import MessageService
from app.services.telegram_sender import TelegramSenderService
from app.services.telegram_service import TelegramService


sent_messages: list[dict] = []
get_file_calls: list[str] = []


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


async def fake_get_file(self, token: str, file_id: str) -> dict:
    get_file_calls.append(file_id)
    return {"file_id": file_id, "file_path": f"photos/{file_id}.jpg"}


TelegramSenderService.send_message = fake_send_message
TelegramSenderService.get_file = fake_get_file


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
                username="runtime_smoke",
                first_name="Runtime smoke",
            ),
        ),
    )


def update_photo(external_chat_id: int, file_id: str, caption: str) -> TelegramUpdate:
    message_id = now_id()
    return TelegramUpdate(
        update_id=message_id,
        message=TelegramMessage(
            message_id=message_id,
            caption=caption,
            chat=TelegramChat(id=external_chat_id),
            from_user=TelegramUser(id=external_chat_id, first_name="Runtime smoke"),
            photo=[
                TelegramFile(file_id=f"{file_id}_small", file_unique_id="small", file_size=10),
                TelegramFile(file_id=file_id, file_unique_id="unique-photo", file_size=1000),
            ],
        ),
    )


async def create_project_and_bot(db):
    stamp = now_id()
    project = Project(
        name=f"Runtime smoke {stamp}",
        slug=f"runtime-smoke-{stamp}",
        sla_threshold_minutes=30,
    )
    db.add(project)
    await db.flush()
    bot = Bot(
        project_id=project.id,
        name="Runtime smoke bot",
        telegram_token="fake-token",
        bot_username="runtime_smoke_bot",
        telegram_bot_id=stamp,
        telegram_first_name="Runtime smoke bot",
    )
    db.add(bot)
    await db.flush()
    return project, bot


async def create_funnel(db, project: Project, bot: Bot, *, input_flow: bool) -> FunnelVersion:
    funnel = Funnel(project_id=project.id, bot_id=bot.id, name=f"Runtime smoke {uuid4()}")
    db.add(funnel)
    await db.flush()
    version = FunnelVersion(
        funnel_id=funnel.id,
        version_number=1,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    db.add(version)
    await db.flush()

    start = FunnelStep(
        funnel_version_id=version.id,
        key=f"start-{uuid4()}",
        title="Старт",
        step_type="trigger",
        block_type="generic_trigger",
        config_json={"trigger_type": "start_command"},
    )
    db.add(start)
    await db.flush()

    if input_flow:
        question = FunnelStep(
            funnel_version_id=version.id,
            key=f"question-{uuid4()}",
            title="Имя",
            step_type="input",
            block_type="generic_input",
            config_json={"prompt": "Как вас зовут?", "save_to": "name"},
        )
        final = FunnelStep(
            funnel_version_id=version.id,
            key=f"final-{uuid4()}",
            title="Ответ",
            step_type="message",
            block_type="generic_message",
            config_json={"text": "Спасибо, записали."},
        )
        db.add_all([question, final])
        await db.flush()
        db.add_all(
            [
                FunnelEdge(funnel_version_id=version.id, from_step_id=start.id, to_step_id=question.id),
                FunnelEdge(funnel_version_id=version.id, from_step_id=question.id, to_step_id=final.id),
            ]
        )
    else:
        message = FunnelStep(
            funnel_version_id=version.id,
            key=f"message-{uuid4()}",
            title="Сообщение",
            step_type="message",
            block_type="generic_message",
            config_json={"text": "Активная воронка отвечает."},
        )
        db.add(message)
        await db.flush()
        db.add(FunnelEdge(funnel_version_id=version.id, from_step_id=start.id, to_step_id=message.id))

    bot.active_funnel_id = funnel.id
    bot.active_funnel_version_id = version.id
    await db.flush()
    return version


async def latest_bot_message(db, chat_id):
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id, Message.sender_type == SenderType.BOT)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def main() -> None:
    async with get_db_session() as db:
        print("smoke: setup")
        project, bot = await create_project_and_bot(db)
        await create_funnel(db, project, bot, input_flow=False)
        await db.commit()

        print("smoke: start_message")
        external_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(external_chat_id, "/start"), bot.id)
        await db.commit()

        chat = await ChatRepository(db).get_by_external(project.id, str(external_chat_id), bot_id=bot.id)
        if chat is None:
            raise SystemExit("chat was not created")
        message = await latest_bot_message(db, chat.id)
        if message is None or message.body != "Активная воронка отвечает.":
            raise SystemExit("Start -> Message did not send active funnel text")
        if not sent_messages or sent_messages[-1]["text"] != "Активная воронка отвечает.":
            raise SystemExit("Telegram sender did not receive active funnel text")

        print("smoke: input_flow")
        await create_funnel(db, project, bot, input_flow=True)
        await db.commit()

        input_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "/start"), bot.id)
        await db.commit()
        input_chat = await ChatRepository(db).get_by_external(project.id, str(input_chat_id), bot_id=bot.id)
        if input_chat is None:
            raise SystemExit("input chat was not created")
        question = await latest_bot_message(db, input_chat.id)
        if question is None or question.body != "Как вас зовут?":
            raise SystemExit("Start -> Input did not ask the question")

        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "Алиса"), bot.id)
        await db.commit()
        final = await latest_bot_message(db, input_chat.id)
        if final is None or final.body != "Спасибо, записали.":
            raise SystemExit("Input answer did not advance to next message")
        lead = await LeadRepository(db).get_by_chat(input_chat.id, project.id)
        if lead is None or lead.name != "Алиса":
            raise SystemExit("Input answer was not mapped to lead.name")

        print("smoke: media")
        media_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_photo(media_chat_id, "photo_file_id", "Фото клиента"), bot.id)
        await db.commit()
        media_chat = await ChatRepository(db).get_by_external(project.id, str(media_chat_id), bot_id=bot.id)
        if media_chat is None:
            raise SystemExit("media chat was not created")
        result = await db.execute(
            select(Message)
            .where(Message.chat_id == media_chat.id, Message.sender_type == SenderType.USER)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        media_message = result.scalar_one_or_none()
        if (
            media_message is None
            or media_message.message_type != MessageType.PHOTO
            or media_message.body is not None
            or media_message.caption != "Фото клиента"
            or media_message.telegram_file_id != "photo_file_id"
        ):
            raise SystemExit("photo metadata was not stored correctly")

        response = await MessageService(db).media_response(media_message.id, project.id)
        if response.media_type != "image/jpeg" or get_file_calls != ["photo_file_id"]:
            raise SystemExit("media proxy did not prepare lazy Telegram getFile response")

        print("smoke: reset")
        actor = (await db.execute(select(User).where(User.email == "admin@testcrm.dev"))).scalar_one_or_none()
        if actor is not None:
            await ChatService(db).reset_chat(input_chat.id, project.id, actor.id)
            await db.commit()
            await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "/start"), bot.id)
            await db.commit()
            restarted = await latest_bot_message(db, input_chat.id)
            if restarted is None or restarted.body != "Как вас зовут?":
                raise SystemExit("reset + /start did not restart active funnel")

    print("ok telegram_runtime_v1")


if __name__ == "__main__":
    asyncio.run(main())
