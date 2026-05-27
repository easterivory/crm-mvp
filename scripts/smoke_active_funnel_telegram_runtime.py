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
from app.core.constants import TrackingCostModel
from app.core.database import get_db_session
from app.models.bot import Bot, BotStep, BotVersion
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead, LeadTag
from app.models.message import Message
from app.models.project import Project
from app.models.role import Role
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.models.user import User
from app.repositories.lead_repository import LeadRepository
from app.schemas.chat import ChatFilters
from app.schemas.funnel import FunnelCreate, FunnelEdgeIn, FunnelGraphIn, FunnelStepIn
from app.schemas.telegram import TelegramCallbackQuery, TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from app.services.chat_service import ChatService
from app.services.funnel_service import FunnelService
from app.services.message_service import MessageService
from app.services.telegram_sender import TelegramSenderService
from app.services.telegram_service import TelegramService
from app.workers.funnel_scheduled_worker import run_once as run_funnel_jobs


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


async def fake_answer_callback_query(self, token, callback_query_id, text=None) -> None:
    return None


TelegramSenderService.answer_callback_query = fake_answer_callback_query


def now_id() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)


def sent_count(text: str) -> int:
    return sum(1 for message in sent_messages if message["text"] == text)


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


def update_callback(external_chat_id: int, data: str, callback_id: str | None = None) -> TelegramUpdate:
    message_id = now_id()
    return TelegramUpdate(
        update_id=message_id,
        callback_query=TelegramCallbackQuery(
            id=callback_id or f"cb_{message_id}",
            data=data,
            message=TelegramMessage(
                message_id=message_id,
                text="button source",
                chat=TelegramChat(id=external_chat_id),
                from_user=TelegramUser(
                    id=external_chat_id,
                    username="active_funnel_smoke",
                    first_name="Active funnel smoke",
                ),
            ),
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
    finish_id = uuid4()
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
                FunnelStepIn(
                    id=finish_id,
                    key="finish",
                    title="Финиш",
                    step_type="finish",
                    block_type="generic_finish",
                    config_json={"result": "success"},
                ),
            ],
            edges=[
                FunnelEdgeIn(
                    from_step_id=start_id,
                    to_step_id=message_id,
                ),
                FunnelEdgeIn(
                    from_step_id=message_id,
                    to_step_id=finish_id,
                ),
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
    finish_id = uuid4()
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
                FunnelStepIn(
                    id=finish_id,
                    key="finish",
                    title="Финиш",
                    step_type="finish",
                    block_type="generic_finish",
                    config_json={"result": "stop"},
                ),
            ],
            edges=[
                FunnelEdgeIn(from_step_id=start_id, to_step_id=input_id),
                FunnelEdgeIn(from_step_id=input_id, to_step_id=message_id),
                FunnelEdgeIn(from_step_id=message_id, to_step_id=finish_id),
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


async def publish_multi_message_funnel(
    db,
    project: Project,
    bot: Bot,
    user: User,
    first_text: str,
    delayed_text: str,
) -> None:
    service = FunnelService(db)
    funnel = await service.create_funnel(
        project_id=project.id,
        data=FunnelCreate(project_id=project.id, bot_id=bot.id, name=f"Multi message {uuid4()}"),
        current_user=user,
    )
    assert funnel.draft_version_id is not None
    start_id = uuid4()
    message_id = uuid4()
    finish_id = uuid4()
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
                    config_json={
                        "messages": [
                            {
                                "id": "msg_1",
                                "type": "text",
                                "text": first_text,
                                "delay_seconds": 0,
                                "buttons": [],
                            },
                            {
                                "id": "msg_2",
                                "type": "text",
                                "text": delayed_text,
                                "delay_seconds": 1,
                                "buttons": [],
                            },
                        ],
                    },
                ),
                FunnelStepIn(
                    id=finish_id,
                    key="finish",
                    title="Финиш",
                    step_type="finish",
                    block_type="generic_finish",
                    config_json={"result": "stop"},
                ),
            ],
            edges=[
                FunnelEdgeIn(from_step_id=start_id, to_step_id=message_id),
                FunnelEdgeIn(from_step_id=message_id, to_step_id=finish_id),
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


async def publish_button_branch_funnel(
    db,
    project: Project,
    bot: Bot,
    user: User,
    prompt: str,
    yes_text: str,
    no_text: str,
) -> None:
    service = FunnelService(db)
    funnel = await service.create_funnel(
        project_id=project.id,
        data=FunnelCreate(project_id=project.id, bot_id=bot.id, name=f"Button branch {uuid4()}"),
        current_user=user,
    )
    assert funnel.draft_version_id is not None
    start_id = uuid4()
    message_id = uuid4()
    yes_id = uuid4()
    no_id = uuid4()
    finish_id = uuid4()
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
                    title="Выбор",
                    step_type="message",
                    block_type="generic_message",
                    config_json={
                        "messages": [
                            {
                                "id": "msg_1",
                                "type": "text",
                                "text": prompt,
                                "delay_seconds": 0,
                                "buttons": [
                                    {
                                        "id": "btn_yes",
                                        "label": "Да",
                                        "value": "yes",
                                        "type": "branch",
                                        "target_step_id": str(yes_id),
                                    },
                                    {
                                        "id": "btn_no",
                                        "label": "Нет",
                                        "value": "no",
                                        "type": "branch",
                                        "target_step_id": str(no_id),
                                    },
                                ],
                            }
                        ],
                    },
                ),
                FunnelStepIn(
                    id=yes_id,
                    key="yes",
                    title="Да",
                    step_type="message",
                    block_type="generic_message",
                    config_json={"text": yes_text},
                ),
                FunnelStepIn(
                    id=no_id,
                    key="no",
                    title="Нет",
                    step_type="message",
                    block_type="generic_message",
                    config_json={"text": no_text},
                ),
                FunnelStepIn(
                    id=finish_id,
                    key="finish",
                    title="Финиш",
                    step_type="finish",
                    block_type="generic_finish",
                    config_json={"result": "stop"},
                ),
            ],
            edges=[
                FunnelEdgeIn(from_step_id=start_id, to_step_id=message_id),
                FunnelEdgeIn(from_step_id=message_id, to_step_id=yes_id, condition_json={"outcome": "yes"}),
                FunnelEdgeIn(from_step_id=yes_id, to_step_id=finish_id),
                FunnelEdgeIn(from_step_id=no_id, to_step_id=finish_id),
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


async def publish_phone_retry_funnel(
    db,
    project: Project,
    bot: Bot,
    user: User,
    prompt: str,
    retry_text: str,
    final_text: str,
) -> None:
    service = FunnelService(db)
    funnel = await service.create_funnel(
        project_id=project.id,
        data=FunnelCreate(project_id=project.id, bot_id=bot.id, name=f"Phone retry {uuid4()}"),
        current_user=user,
    )
    assert funnel.draft_version_id is not None
    start_id = uuid4()
    input_id = uuid4()
    message_id = uuid4()
    finish_id = uuid4()
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
                    key="phone",
                    title="Телефон",
                    step_type="input",
                    block_type="generic_input",
                    config_json={
                        "prompt": prompt,
                        "answer_type": "phone",
                        "save_to": "phone",
                        "validation": {"type": "phone"},
                        "retry_message": retry_text,
                        "max_retries": 2,
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
                FunnelStepIn(
                    id=finish_id,
                    key="finish",
                    title="Финиш",
                    step_type="finish",
                    block_type="generic_finish",
                    config_json={"result": "stop"},
                ),
            ],
            edges=[
                FunnelEdgeIn(from_step_id=start_id, to_step_id=input_id),
                FunnelEdgeIn(from_step_id=input_id, to_step_id=message_id),
                FunnelEdgeIn(from_step_id=message_id, to_step_id=finish_id),
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


async def publish_condition_action_funnel(
    db,
    project: Project,
    bot: Bot,
    user: User,
    prompt: str,
    yes_text: str,
    no_text: str,
) -> None:
    service = FunnelService(db)
    funnel = await service.create_funnel(
        project_id=project.id,
        data=FunnelCreate(project_id=project.id, bot_id=bot.id, name=f"Condition action {uuid4()}"),
        current_user=user,
    )
    assert funnel.draft_version_id is not None
    start_id = uuid4()
    input_id = uuid4()
    condition_id = uuid4()
    action_id = uuid4()
    yes_id = uuid4()
    no_id = uuid4()
    finish_id = uuid4()
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
                    config_json={"prompt": prompt, "answer_type": "text"},
                ),
                FunnelStepIn(
                    id=condition_id,
                    key="condition",
                    title="Условие",
                    step_type="condition",
                    block_type="generic_condition",
                    config_json={
                        "mode": "simple_yes_no",
                        "conditions": [{"id": "cond_1", "source": "last_answer", "operator": "equals", "value": "yes"}],
                        "outcomes": [
                            {"id": "true", "label": "Да", "target_step_id": str(action_id)},
                            {"id": "false", "label": "Нет", "target_step_id": str(no_id)},
                            {"id": "fallback", "label": "Fallback", "target_step_id": str(no_id)},
                        ],
                    },
                ),
                FunnelStepIn(
                    id=action_id,
                    key="action",
                    title="CRM действие",
                    step_type="action",
                    block_type="generic_crm_action",
                    config_json={
                        "actions": [
                            {"id": "action_status", "type": "set_lead_status", "status": "qualified"},
                            {"id": "action_country", "type": "write_field", "field": "country", "value": "DE"},
                        ]
                    },
                ),
                FunnelStepIn(
                    id=yes_id,
                    key="yes",
                    title="Да",
                    step_type="message",
                    block_type="generic_message",
                    config_json={"text": yes_text},
                ),
                FunnelStepIn(
                    id=no_id,
                    key="no",
                    title="Нет",
                    step_type="message",
                    block_type="generic_message",
                    config_json={"text": no_text},
                ),
                FunnelStepIn(
                    id=finish_id,
                    key="finish",
                    title="Финиш",
                    step_type="finish",
                    block_type="generic_finish",
                    config_json={"result": "stop"},
                ),
            ],
            edges=[
                FunnelEdgeIn(from_step_id=start_id, to_step_id=input_id),
                FunnelEdgeIn(from_step_id=input_id, to_step_id=condition_id),
                FunnelEdgeIn(from_step_id=condition_id, to_step_id=action_id, condition_json={"outcome": "true"}),
                FunnelEdgeIn(from_step_id=condition_id, to_step_id=no_id, condition_json={"outcome": "false"}),
                FunnelEdgeIn(from_step_id=action_id, to_step_id=yes_id),
                FunnelEdgeIn(from_step_id=yes_id, to_step_id=finish_id),
                FunnelEdgeIn(from_step_id=no_id, to_step_id=finish_id),
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


async def latest_state(db, chat_id) -> ChatFunnelState | None:
    return (
        await db.execute(select(ChatFunnelState).where(ChatFunnelState.chat_id == chat_id))
    ).scalar_one_or_none()


async def lead_for_chat(db, project: Project, chat: Chat) -> Lead | None:
    return await LeadRepository(db).get_by_chat(chat.id, project.id)


async def api_history_bodies(db, project: Project, chat: Chat) -> list[str | None]:
    messages, _ = await MessageService(db).list_messages(
        chat_id=chat.id,
        project_id=project.id,
        limit=100,
        offset=0,
    )
    return [message.body for message in messages]


async def attach_filter_fixtures(db, project: Project, bot: Bot, chat: Chat, lead: Lead):
    stamp = now_id()
    link = TrackingLink(
        project_id=project.id,
        bot_id=bot.id,
        name=f"Smoke link {stamp}",
        ref_code=f"smoke-ref-{stamp}",
        code=f"smoke-code-{stamp}",
        title=f"Smoke link {stamp}",
        cost_model=TrackingCostModel.FIX_PDP,
    )
    tag = Tag(project_id=project.id, name=f"smoke-tag-{stamp}")
    db.add_all([link, tag])
    await db.flush()
    chat.tracking_link_id = link.id
    db.add(LeadTag(lead_id=lead.id, tag_id=tag.id))
    await db.flush()
    return link, tag


async def assert_chat_filter_contains(
    db,
    project: Project,
    chat: Chat,
    filters: ChatFilters,
    label: str,
) -> None:
    items, _ = await ChatService(db).get_chat_list(
        project_id=project.id,
        filters=filters,
        limit=50,
        offset=0,
    )
    if chat.id not in {item.id for item in items}:
        raise SystemExit(f"chat filter did not include expected chat: {label}")


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
        history = await api_history_bodies(db, project, chat)
        if history[:2] != ["/start", unique_text]:
            raise SystemExit(f"API history did not expose first /start + bot reply: {history!r}")

        state = await latest_state(db, chat.id)
        if state is None or state.funnel_version_id != bot.active_funnel_version_id:
            raise SystemExit("chat_funnel_state was not pinned to active version")
        if state.completed_at is None or state.waiting_for_answer:
            raise SystemExit("Start -> Message -> Finish did not complete state")
        qualified = await LeadRepository(db).get_status_by_code("qualified")
        lead = await lead_for_chat(db, project, chat)
        if qualified is not None and (lead is None or lead.status_id != qualified.id):
            raise SystemExit("generic_finish result=success did not apply qualified status")
        if lead is None:
            raise SystemExit("lead was not created for chat")
        tracking_link, tag = await attach_filter_fixtures(db, project, bot, chat, lead)
        today = datetime.now(timezone.utc).date()
        date_from, date_to = ChatService.date_range_to_datetimes(today, today)
        await assert_chat_filter_contains(
            db,
            project,
            chat,
            ChatFilters(tag_ids=[tag.id]),
            "tag",
        )
        await assert_chat_filter_contains(
            db,
            project,
            chat,
            ChatFilters(lead_statuses=["qualified"]),
            "lead status",
        )
        await assert_chat_filter_contains(
            db,
            project,
            chat,
            ChatFilters(tracking_link_id=tracking_link.id),
            "tracking link",
        )
        await assert_chat_filter_contains(
            db,
            project,
            chat,
            ChatFilters(date_from=date_from, date_to=date_to),
            "date range",
        )
        await assert_chat_filter_contains(
            db,
            project,
            chat,
            ChatFilters(
                tracking_link_id=tracking_link.id,
                tag_ids=[tag.id],
                lead_statuses=["qualified"],
            ),
            "combined tag + status + tracking",
        )

        sent_before = sent_count(unique_text)
        await TelegramService(db).handle_webhook_update(update_text(external_chat_id, "123"), bot.id)
        await db.commit()
        if sent_count(unique_text) != sent_before:
            raise SystemExit("completed funnel repeated first message on normal user text")
        history = await api_history_bodies(db, project, chat)
        if "123" not in history:
            raise SystemExit("post-funnel incoming message was not exposed in API history")
        chat_out = await ChatService(db).get_chat(chat.id, project.id)
        if not chat_out.has_unanswered_incoming or chat_out.lifecycle_status != "manual":
            raise SystemExit("post-funnel message did not mark chat as manual/unanswered")

        await TelegramService(db).handle_webhook_update(update_text(external_chat_id, "/start"), bot.id)
        await db.commit()
        if sent_count(unique_text) != sent_before:
            raise SystemExit("completed funnel restarted on repeated /start")
        history = await api_history_bodies(db, project, chat)
        if history.count("/start") < 2:
            raise SystemExit("repeated /start was not exposed in API history")

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
        input_state = await latest_state(db, input_chat.id)
        if input_state is None or not input_state.waiting_for_answer or input_state.completed_at is not None:
            raise SystemExit("Start -> Input did not set waiting_for_answer")

        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "Алиса"), bot.id)
        await db.commit()
        final = await latest_message(db, input_chat.id, SenderType.BOT)
        if final is None or final.body != final_text:
            raise SystemExit("Input answer did not advance to next active funnel message")
        if final.body == OLD_FALLBACK_TEXT:
            raise SystemExit("legacy fallback text was used after input answer")
        input_state = await latest_state(db, input_chat.id)
        if input_state is None or input_state.completed_at is None or input_state.waiting_for_answer:
            raise SystemExit("Start -> Input -> Message -> Finish did not complete state")
        input_lead = await lead_for_chat(db, project, input_chat)
        if input_lead is None or input_lead.name != "Алиса":
            raise SystemExit("Input answer was not mapped to lead.name")

        final_before = sent_count(final_text)
        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "после финиша"), bot.id)
        await db.commit()
        if sent_count(final_text) != final_before:
            raise SystemExit("completed input funnel restarted after later user message")
        input_history = await api_history_bodies(db, project, input_chat)
        if "после финиша" not in input_history:
            raise SystemExit("post-funnel input chat message was not exposed in API history")

        await ChatService(db).reset_chat(input_chat.id, project.id, user.id)
        await db.commit()
        await TelegramService(db).handle_webhook_update(update_text(input_chat_id, "/start"), bot.id)
        await db.commit()
        restarted_chat = await chat_by_external(db, project, bot, input_chat_id)
        restarted_question = await latest_message(db, restarted_chat.id, SenderType.BOT)
        if restarted_question is None or restarted_question.body != prompt:
            raise SystemExit("reset + /start did not start active funnel again")
        restarted_history = await api_history_bodies(db, project, restarted_chat)
        if restarted_history[:2] != ["/start", prompt]:
            raise SystemExit(
                f"reset API history did not expose first /start + prompt: {restarted_history!r}"
            )
        if sent_count(prompt) < 2:
            raise SystemExit("reset did not allow a fresh active funnel start")

        first_text = f"SMOKE_MULTI_FIRST_{now_id()}"
        delayed_text = f"SMOKE_MULTI_DELAYED_{now_id()}"
        await publish_multi_message_funnel(db, project, bot, user, first_text, delayed_text)
        await db.commit()
        await db.refresh(bot)
        multi_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(multi_chat_id, "/start"), bot.id)
        await db.commit()
        multi_chat = await chat_by_external(db, project, bot, multi_chat_id)
        if sent_count(first_text) != 1:
            raise SystemExit("multi-message block did not send first message immediately")
        if sent_count(delayed_text) != 0:
            raise SystemExit("delayed multi-message was sent before scheduled job")
        await asyncio.sleep(1.1)
        processed_jobs = await run_funnel_jobs()
        if processed_jobs < 1 or sent_count(delayed_text) != 1:
            raise SystemExit("scheduled multi-message job did not send delayed message")
        multi_state = await latest_state(db, multi_chat.id)
        if multi_state is None or multi_state.completed_at is None:
            raise SystemExit("multi-message funnel did not finish after delayed sequence")

        button_prompt = f"SMOKE_BUTTON_PROMPT_{now_id()}"
        yes_text = f"SMOKE_BUTTON_YES_{now_id()}"
        no_text = f"SMOKE_BUTTON_NO_{now_id()}"
        await publish_button_branch_funnel(db, project, bot, user, button_prompt, yes_text, no_text)
        await db.commit()
        await db.refresh(bot)
        button_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(button_chat_id, "/start"), bot.id)
        await db.commit()
        button_chat = await chat_by_external(db, project, bot, button_chat_id)
        button_state = await latest_state(db, button_chat.id)
        if button_state is None or not button_state.waiting_for_answer:
            raise SystemExit("button message did not set waiting_for_answer")
        button_message = sent_messages[-1]
        callback_data = button_message["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await TelegramService(db).handle_webhook_update(update_callback(button_chat_id, callback_data), bot.id)
        await db.commit()
        if sent_count(yes_text) != 1 or sent_count(no_text) != 0:
            raise SystemExit("button branch did not route to target_step_id")

        phone_prompt = f"SMOKE_PHONE_PROMPT_{now_id()}"
        retry_text = f"SMOKE_PHONE_RETRY_{now_id()}"
        phone_final = f"SMOKE_PHONE_FINAL_{now_id()}"
        await publish_phone_retry_funnel(db, project, bot, user, phone_prompt, retry_text, phone_final)
        await db.commit()
        await db.refresh(bot)
        phone_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(phone_chat_id, "/start"), bot.id)
        await db.commit()
        await TelegramService(db).handle_webhook_update(update_text(phone_chat_id, "abc"), bot.id)
        await db.commit()
        if sent_count(retry_text) != 1:
            raise SystemExit("invalid phone answer did not trigger retry message")
        await TelegramService(db).handle_webhook_update(update_text(phone_chat_id, "+1 555 123 4567"), bot.id)
        await db.commit()
        if sent_count(phone_final) != 1:
            raise SystemExit("valid phone answer did not advance after retry")

        condition_prompt = f"SMOKE_CONDITION_PROMPT_{now_id()}"
        condition_yes = f"SMOKE_CONDITION_YES_{now_id()}"
        condition_no = f"SMOKE_CONDITION_NO_{now_id()}"
        await publish_condition_action_funnel(db, project, bot, user, condition_prompt, condition_yes, condition_no)
        await db.commit()
        await db.refresh(bot)
        condition_chat_id = now_id()
        await TelegramService(db).handle_webhook_update(update_text(condition_chat_id, "/start"), bot.id)
        await db.commit()
        await TelegramService(db).handle_webhook_update(update_text(condition_chat_id, "да"), bot.id)
        await db.commit()
        condition_chat = await chat_by_external(db, project, bot, condition_chat_id)
        condition_lead = await lead_for_chat(db, project, condition_chat)
        if sent_count(condition_yes) != 1 or sent_count(condition_no) != 0:
            raise SystemExit("condition simple_yes_no did not route true branch")
        qualified_status = await LeadRepository(db).get_status_by_code("qualified")
        if (
            condition_lead is None
            or condition_lead.country != "DE"
            or (qualified_status is not None and condition_lead.status_id != qualified_status.id)
        ):
            raise SystemExit("CRM action did not write lead field/status")

    print("ok active_funnel_telegram_runtime")


if __name__ == "__main__":
    asyncio.run(main())
