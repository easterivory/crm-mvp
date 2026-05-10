"""
BotEngineService - extensible bot scenario state machine.

Step execution is implemented via handlers keyed by BotStep.step_type. Adding
a new step type means implementing StepHandler.execute() and registering it in
BotEngineService.handlers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MessageType, SenderType
from app.models.bot import BotStep, ChatBotState
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.tracking_repository import TrackingRepository
from app.schemas.message import MessageCreate, MessageOut
from app.services.message_service import MessageService


class StepHandler(ABC):
    @abstractmethod
    async def execute(
        self,
        state: ChatBotState,
        step: BotStep,
        user_message: Optional[MessageOut] = None,
    ) -> Optional[UUID]:
        """Execute a step and return the next step id, current id, or None."""


class SendMessageHandler(StepHandler):
    def __init__(self, bot_repo: BotRepository, message_service: MessageService) -> None:
        self.bot_repo = bot_repo
        self.message_service = message_service

    async def execute(
        self,
        state: ChatBotState,
        step: BotStep,
        user_message: Optional[MessageOut] = None,
    ) -> Optional[UUID]:
        text = str(step.config.get("text") or "").strip()
        if not text:
            return step.fallback_step_id

        project_id = await self.bot_repo.get_project_id_for_bot_version(
            state.bot_version_id
        )
        if project_id is None:
            return step.fallback_step_id

        await self.message_service.create_message(
            chat_id=state.chat_id,
            project_id=project_id,
            data=MessageCreate(
                message_type=MessageType.TEXT,
                sender_type=SenderType.BOT,
                sender_id=None,
                body=text,
            ),
        )
        return step.next_step_id


class WaitInputHandler(StepHandler):
    async def execute(
        self,
        state: ChatBotState,
        step: BotStep,
        user_message: Optional[MessageOut] = None,
    ) -> Optional[UUID]:
        if user_message is None:
            return step.id

        variable_name = str(step.config.get("variable_name") or "").strip()
        if variable_name:
            variables = dict(state.variables or {})
            variables[variable_name] = user_message.body
            state.variables = variables

        return step.next_step_id


class BotEngineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.chat_repo = ChatRepository(db)
        self.tracking_repo = TrackingRepository(db)
        self.message_service = MessageService(db)
        self.handlers: dict[str, StepHandler] = {
            "send_message": SendMessageHandler(self.bot_repo, self.message_service),
            "wait_input": WaitInputHandler(),
        }

    async def initialize_chat(self, chat_id: UUID, project_id: UUID) -> None:
        active_version = await self._resolve_initial_bot_version(chat_id, project_id)
        if active_version is None:
            return

        current_step_id = active_version.start_step_id
        tracking_target_step_id = await self._resolve_tracking_target_step_id(
            chat_id=chat_id,
            project_id=project_id,
            bot_version_id=active_version.id,
        )
        if tracking_target_step_id is not None:
            current_step_id = tracking_target_step_id

        existing = await self.bot_repo.get_chat_state(chat_id)
        if existing is not None:
            return

        try:
            async with self.db.begin_nested():
                await self.bot_repo.create_chat_state(
                    chat_id=chat_id,
                    bot_version_id=active_version.id,
                    current_step_id=current_step_id,
                )
        except IntegrityError:
            return

        await self.process_chat(chat_id)

    async def _resolve_initial_bot_version(self, chat_id: UUID, project_id: UUID):
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is not None and chat.tracking_link_id is not None:
            link = await self.tracking_repo.get_by_id_in_project(
                chat.tracking_link_id,
                project_id,
            )
            if link is not None:
                version = await self.bot_repo.get_active_version_for_bot(
                    link.bot_id,
                    project_id,
                )
                if version is not None:
                    return version

        return await self.bot_repo.get_active_version_for_project(project_id)

    async def _resolve_tracking_target_step_id(
        self,
        chat_id: UUID,
        project_id: UUID,
        bot_version_id: UUID,
    ) -> Optional[UUID]:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None or chat.tracking_link_id is None:
            return None

        link = await self.tracking_repo.get_by_id_in_project(
            chat.tracking_link_id,
            project_id,
        )
        if link is None or link.target_step_id is None:
            return None

        belongs = await self.bot_repo.step_belongs_to_version(
            link.target_step_id,
            bot_version_id,
        )
        return link.target_step_id if belongs else None

    async def process_chat(
        self,
        chat_id: UUID,
        user_message: Optional[MessageOut] = None,
    ) -> None:
        state = await self.bot_repo.get_chat_state(chat_id)
        if state is None or not state.is_active:
            return

        current_step_id = state.current_step_id
        variables = dict(state.variables or {})

        while current_step_id is not None:
            step = await self.bot_repo.get_step(current_step_id)
            if step is None:
                current_step_id = None
                break

            handler = self.handlers.get(step.step_type)
            if handler is None:
                current_step_id = step.fallback_step_id
                if current_step_id is None:
                    break
                continue

            state.current_step_id = current_step_id
            state.variables = variables

            next_step_id = await handler.execute(
                state=state,
                step=step,
                user_message=user_message,
            )
            variables = dict(state.variables or {})

            if next_step_id == step.id:
                current_step_id = step.id
                break
            if next_step_id is None:
                current_step_id = None
                break

            current_step_id = next_step_id
            user_message = None

        await self.bot_repo.update_chat_state(
            chat_id=chat_id,
            current_step_id=current_step_id,
            variables=variables,
        )
        await self.db.commit()
