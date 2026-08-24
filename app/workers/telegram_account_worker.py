from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from telethon import TelegramClient, events, functions, types
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession

from app.core.config import settings
from app.core.database import get_db_session
from app.core.redis import close_redis, get_redis
from app.models.bot import TelegramUserConnection
from app.models.chat import Chat
from app.repositories.telegram_user_connection_repository import (
    TelegramUserConnectionRepository,
)
from app.schemas.telegram import (
    TelegramAudio,
    TelegramChat,
    TelegramDocument,
    TelegramFile,
    TelegramMessage,
    TelegramSticker,
    TelegramUpdate,
    TelegramUser,
    TelegramVideo,
    TelegramVoice,
)
from app.services.operational_alert_service import send_operational_alert
from app.services.telegram_account_credential_service import (
    TelegramAccountCredentialService,
)
from app.services.telegram_account_gateway import TELEGRAM_ACCOUNT_COMMAND_QUEUE
from app.services.telegram_service import TelegramService


logger = logging.getLogger(__name__)
PROCESSING_QUEUE = f"{TELEGRAM_ACCOUNT_COMMAND_QUEUE}:processing"


class TelegramAccountWorker:
    def __init__(self) -> None:
        self.credentials = TelegramAccountCredentialService()
        self.clients: dict[UUID, TelegramClient] = {}
        self.connection_tasks: dict[UUID, asyncio.Task[None]] = {}
        self.pending_crm_outgoing: dict[UUID, dict[str, list[float]]] = defaultdict(dict)
        self.dialogs_hydrated: set[UUID] = set()
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        redis = await get_redis()
        await self._recover_interrupted_commands(redis)
        supervisor = asyncio.create_task(self._supervise_connections())
        commands = asyncio.create_task(self._consume_commands())
        try:
            await asyncio.gather(supervisor, commands)
        finally:
            self._stopping.set()
            for task in self.connection_tasks.values():
                task.cancel()
            await asyncio.gather(*self.connection_tasks.values(), return_exceptions=True)
            for client in tuple(self.clients.values()):
                await client.disconnect()
            await close_redis()

    async def _supervise_connections(self) -> None:
        interval = max(settings.TELEGRAM_ACCOUNT_SUPERVISOR_INTERVAL_SECONDS, 2)
        while not self._stopping.is_set():
            try:
                await self._refresh_connections()
            except Exception as exc:
                logger.exception("Could not refresh Telegram account connections")
                await send_operational_alert(
                    component="telegram_account_worker",
                    title="Telegram work account supervisor failed",
                    details={"error": self._safe_error(exc)},
                    dedupe_key=(
                        "telegram-account-supervisor:"
                        f"{exc.__class__.__name__}"
                    ),
                )
            await asyncio.sleep(interval)

    async def _refresh_connections(self) -> None:
        async with get_db_session() as db:
            connections = await TelegramUserConnectionRepository(db).list_authorized()
            # Rollback expires ORM attributes. Snapshot primitive IDs while
            # the rows are still attached to this session so the supervisor
            # never triggers an async lazy load after the context closes.
            active_ids = {connection.bot_id for connection in connections}
            await db.rollback()

        for bot_id, task in tuple(self.connection_tasks.items()):
            if task.done() or bot_id not in active_ids:
                if not task.done():
                    task.cancel()
                self.connection_tasks.pop(bot_id, None)
        for bot_id in active_ids:
            if bot_id not in self.connection_tasks:
                self.connection_tasks[bot_id] = asyncio.create_task(
                    self._run_connection(bot_id)
                )

    async def _run_connection(self, bot_id: UUID) -> None:
        backoff = 2
        while not self._stopping.is_set():
            client: TelegramClient | None = None
            try:
                api_id, project_id, api_hash, session = await self._load_connection(bot_id)
                if api_id is None or project_id is None:
                    return
                await self._set_connection_state(bot_id, "connecting", None)
                client = TelegramClient(
                    StringSession(session),
                    api_id,
                    api_hash,
                    device_model="Sfera CRM",
                    system_version="Server",
                    app_version="1.0",
                    sequential_updates=True,
                    auto_reconnect=True,
                    connection_retries=5,
                    retry_delay=2,
                )
                self._register_handlers(
                    client=client,
                    bot_id=bot_id,
                    project_id=project_id,
                )
                await client.connect()
                if not await client.is_user_authorized():
                    await self._mark_authorization_lost(bot_id)
                    return
                try:
                    await self._sync_missed_messages(
                        client=client,
                        bot_id=bot_id,
                        project_id=project_id,
                    )
                except Exception as exc:
                    logger.exception("MTProto catch-up failed bot_id=%s", bot_id)
                    await send_operational_alert(
                        component="telegram_account_worker",
                        title="Telegram work account catch-up failed",
                        details={"bot_id": bot_id, "error": self._safe_error(exc)},
                        dedupe_key=f"telegram-account-catch-up:{bot_id}:{exc.__class__.__name__}",
                    )
                # Do not expose the client to the command consumer until the
                # reconnect catch-up has read its cursor. Otherwise an outgoing
                # CRM command could advance connection state while older inbound
                # updates are still being restored.
                self.clients[bot_id] = client
                await self._set_connection_state(bot_id, "connected", None)
                logger.info("MTProto account connected bot_id=%s", bot_id)
                backoff = 2
                await client.run_until_disconnected()
                if not self._stopping.is_set():
                    raise ConnectionError("MTProto client disconnected")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("MTProto account connection failed bot_id=%s", bot_id)
                await self._set_connection_state(bot_id, "error", self._safe_error(exc))
                await send_operational_alert(
                    component="telegram_account_worker",
                    title="Telegram work account connection failed",
                    details={"bot_id": bot_id, "error": self._safe_error(exc)},
                    dedupe_key=f"telegram-account:{bot_id}:{exc.__class__.__name__}",
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                if self.clients.get(bot_id) is client:
                    self.clients.pop(bot_id, None)
                self.dialogs_hydrated.discard(bot_id)
                if client is not None:
                    await client.disconnect()

    def _register_handlers(
        self,
        *,
        client: TelegramClient,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        async def new_message(event: events.NewMessage.Event) -> None:
            if not event.is_private:
                return
            peer = await event.get_chat()
            if not self._is_supported_private_peer(peer):
                return
            manual_outgoing = True
            if event.out:
                fingerprint = self._event_fingerprint(event)
                manual_outgoing = not self._consume_pending(bot_id, fingerprint)
                if not manual_outgoing:
                    # CRM-originated sends are persisted by MessageService after
                    # the RPC returns. Persisting the echoed MTProto update here
                    # would race that write and could lose the manager author.
                    return
            await self._process_new_message(
                client=client,
                event=event,
                bot_id=bot_id,
                project_id=project_id,
                manual_outgoing=manual_outgoing,
            )

        async def edited_message(event: events.MessageEdited.Event) -> None:
            if not event.is_private:
                return
            try:
                await self._process_edited_message(
                    event=event,
                    bot_id=bot_id,
                    project_id=project_id,
                )
            except Exception:
                logger.exception(
                    "MTProto edit synchronization failed bot_id=%s message_id=%s",
                    bot_id,
                    getattr(event.message, "id", None),
                )

        async def deleted_message(event: events.MessageDeleted.Event) -> None:
            try:
                await self._process_deleted_message(
                    event=event,
                    bot_id=bot_id,
                    project_id=project_id,
                )
            except Exception:
                logger.exception(
                    "MTProto delete synchronization failed bot_id=%s ids=%s",
                    bot_id,
                    event.deleted_ids,
                )

        client.add_event_handler(new_message, events.NewMessage())
        client.add_event_handler(edited_message, events.MessageEdited())
        client.add_event_handler(deleted_message, events.MessageDeleted())

    async def _process_new_message(
        self,
        *,
        client: TelegramClient,
        event: events.NewMessage.Event,
        bot_id: UUID,
        project_id: UUID,
        manual_outgoing: bool,
    ) -> None:
        try:
            update = await self._telegram_update(client, event, bot_id=bot_id)
            for attempt in range(3):
                try:
                    async with get_db_session() as db:
                        service = TelegramService(db)
                        if event.out:
                            await service.handle_mtproto_outgoing_message(
                                update=update,
                                project_id=project_id,
                                bot_id=bot_id,
                                manual_outgoing=manual_outgoing,
                            )
                        else:
                            await service.handle_update(
                                update=update,
                                project_id=project_id,
                                bot_id=bot_id,
                                source_transport="user_mtproto",
                            )
                        await db.commit()
                        await service.dispatch_post_commit_actions()
                    await self._touch_last_sync(bot_id)
                    return
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
        except Exception as exc:
            logger.exception(
                "MTProto message processing failed bot_id=%s message_id=%s",
                bot_id,
                getattr(event.message, "id", None),
            )
            await send_operational_alert(
                component="telegram_account_worker",
                title="Telegram work account message processing failed",
                details={
                    "bot_id": bot_id,
                    "message_id": getattr(event.message, "id", None),
                    "error": self._safe_error(exc),
                },
                dedupe_key=f"telegram-account-message:{bot_id}:{exc.__class__.__name__}",
            )

    async def _process_edited_message(
        self,
        *,
        event: events.MessageEdited.Event,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        peer_id = self._peer_id(event)
        text = str(event.message.message or "")
        is_caption = event.message.media is not None
        async with get_db_session() as db:
            await TelegramService(db).handle_mtproto_message_edit(
                external_chat_id=str(peer_id),
                external_message_id=str(event.message.id),
                project_id=project_id,
                bot_id=bot_id,
                text=text,
                is_caption=is_caption,
                edited_at=event.message.edit_date or datetime.now(timezone.utc),
            )
            await db.commit()

    async def _process_deleted_message(
        self,
        *,
        event: events.MessageDeleted.Event,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        chat_id = event.chat_id
        if chat_id is None:
            async with get_db_session() as db:
                await TelegramService(db).handle_mtproto_message_delete_without_peer(
                    external_message_ids=[str(item) for item in event.deleted_ids],
                    bot_id=bot_id,
                    deleted_at=datetime.now(timezone.utc),
                )
                await db.commit()
            return
        async with get_db_session() as db:
            await TelegramService(db).handle_mtproto_message_delete(
                external_chat_id=str(chat_id),
                external_message_ids=[str(item) for item in event.deleted_ids],
                project_id=project_id,
                bot_id=bot_id,
                deleted_at=datetime.now(timezone.utc),
            )
            await db.commit()

    async def _telegram_update(
        self,
        client: TelegramClient,
        event: events.NewMessage.Event,
        *,
        bot_id: UUID,
    ) -> TelegramUpdate:
        peer = await event.get_chat()
        if peer is None or getattr(peer, "id", None) is None:
            raise RuntimeError("Telegram private peer is unavailable")
        input_peer = await event.get_input_chat()
        return await self._telegram_update_from_message(
            client=client,
            message=event.message,
            peer=peer,
            input_peer=input_peer,
            bot_id=bot_id,
        )

    async def _telegram_update_from_message(
        self,
        *,
        client: TelegramClient,
        message: Any,
        peer: Any,
        input_peer: Any,
        bot_id: UUID,
        max_media_bytes: int | None = None,
    ) -> TelegramUpdate:
        access_hash = getattr(input_peer, "access_hash", None)
        user = TelegramUser(
            id=int(peer.id),
            username=getattr(peer, "username", None),
            first_name=getattr(peer, "first_name", None),
            last_name=getattr(peer, "last_name", None),
        )
        chat = TelegramChat(
            id=int(peer.id),
            type="private",
            username=getattr(peer, "username", None),
            access_hash=int(access_hash) if access_hash is not None else None,
        )
        local_path = await self._download_media(
            client=client,
            message=message,
            bot_id=bot_id,
            peer_id=int(peer.id),
            max_bytes=max_media_bytes,
        )
        telegram_message = self._message_schema(
            message,
            chat=chat,
            peer_user=user,
            local_path=local_path,
        )
        return TelegramUpdate(update_id=int(message.id), message=telegram_message)

    async def _sync_missed_messages(
        self,
        *,
        client: TelegramClient,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        last_synced_at, own_user_id, initial_sync_required = await self._load_sync_cursor(
            bot_id
        )
        if initial_sync_required:
            await self._sync_initial_dialogs(
                client=client,
                bot_id=bot_id,
                project_id=project_id,
                own_user_id=own_user_id,
            )
            await self._touch_last_sync(bot_id)
            return
        if last_synced_at is None:
            await self._touch_last_sync(bot_id)
            return

        threshold = last_synced_at - timedelta(minutes=2)
        processed = 0
        async for dialog in client.iter_dialogs(limit=None):
            dialog_date = self._as_utc(getattr(dialog, "date", None))
            if dialog_date is not None and dialog_date < threshold:
                # Pinned dialogs may appear before newer regular dialogs.
                continue
            if not bool(getattr(dialog, "is_user", False)):
                continue
            peer = getattr(dialog, "entity", None)
            input_peer = getattr(dialog, "input_entity", None)
            peer_id = getattr(peer, "id", None)
            if (
                peer is None
                or input_peer is None
                or peer_id is None
                or int(peer_id) == own_user_id
                or bool(getattr(peer, "bot", False))
            ):
                continue

            missed: list[Any] = []
            async for message in client.iter_messages(input_peer, limit=None):
                message_date = self._as_utc(getattr(message, "date", None))
                if message_date is not None and message_date < threshold:
                    break
                if getattr(message, "action", None) is not None:
                    continue
                if getattr(message, "message", None) is None and getattr(message, "media", None) is None:
                    continue
                missed.append(message)

            for message in reversed(missed):
                if bool(getattr(message, "out", False)) and await self._sync_existing_outgoing(
                    message=message,
                    peer_id=int(peer_id),
                    bot_id=bot_id,
                    project_id=project_id,
                ):
                    continue
                update = await self._telegram_update_from_message(
                    client=client,
                    message=message,
                    peer=peer,
                    input_peer=input_peer,
                    bot_id=bot_id,
                )
                async with get_db_session() as db:
                    service = TelegramService(db)
                    if bool(getattr(message, "out", False)):
                        await service.handle_mtproto_outgoing_message(
                            update=update,
                            project_id=project_id,
                            bot_id=bot_id,
                            manual_outgoing=True,
                        )
                    else:
                        await service.handle_update(
                            update=update,
                            project_id=project_id,
                            bot_id=bot_id,
                            source_transport="user_mtproto",
                        )
                    await db.commit()
                    await service.dispatch_post_commit_actions()
                processed += 1

        await self._touch_last_sync(bot_id)
        if processed:
            logger.info(
                "MTProto catch-up synchronized bot_id=%s messages=%s since=%s",
                bot_id,
                processed,
                last_synced_at.isoformat(),
            )

    async def _sync_initial_dialogs(
        self,
        *,
        client: TelegramClient,
        bot_id: UUID,
        project_id: UUID,
        own_user_id: int | None,
    ) -> None:
        dialog_limit = max(
            1,
            min(settings.TELEGRAM_ACCOUNT_INITIAL_SYNC_DIALOG_LIMIT, 5000),
        )
        messages_per_dialog = max(
            1,
            min(settings.TELEGRAM_ACCOUNT_INITIAL_SYNC_MESSAGES_PER_DIALOG, 200),
        )
        max_media_bytes = (
            max(settings.TELEGRAM_ACCOUNT_INITIAL_SYNC_MEDIA_MAX_MB, 0)
            * 1024
            * 1024
        )
        total_media_budget = (
            max(settings.TELEGRAM_ACCOUNT_INITIAL_SYNC_TOTAL_MEDIA_MAX_MB, 0)
            * 1024
            * 1024
        )
        imported_media_bytes = 0
        imported_dialogs = 0
        imported_messages = 0
        failed_messages = 0
        attempted_messages = 0
        eligible_dialogs = 0

        async for dialog in client.iter_dialogs(limit=None):
            if not bool(getattr(dialog, "is_user", False)):
                continue
            peer = getattr(dialog, "entity", None)
            input_peer = getattr(dialog, "input_entity", None)
            peer_id = getattr(peer, "id", None)
            if (
                peer is None
                or input_peer is None
                or peer_id is None
                or int(peer_id) == own_user_id
                or not self._is_supported_private_peer(peer)
            ):
                continue
            if eligible_dialogs >= dialog_limit:
                break
            eligible_dialogs += 1

            history: list[Any] = []
            async for message in client.iter_messages(
                input_peer,
                limit=messages_per_dialog,
            ):
                if getattr(message, "action", None) is not None:
                    continue
                if (
                    getattr(message, "message", None) is None
                    and getattr(message, "media", None) is None
                ):
                    continue
                history.append(message)

            imported_chat_id: UUID | None = None
            for message in reversed(history):
                attempted_messages += 1
                try:
                    remaining_media_budget = max(
                        total_media_budget - imported_media_bytes,
                        0,
                    )
                    message_media_limit = min(
                        max_media_bytes,
                        remaining_media_budget,
                    )
                    update = await self._telegram_update_from_message(
                        client=client,
                        message=message,
                        peer=peer,
                        input_peer=input_peer,
                        bot_id=bot_id,
                        max_media_bytes=message_media_limit,
                    )
                    imported_media_bytes += self._local_media_bytes(update)
                    sent_at = self._as_utc(getattr(message, "date", None))
                    if sent_at is None:
                        sent_at = datetime.now(timezone.utc)
                    async with get_db_session() as db:
                        service = TelegramService(db)
                        result = await service.handle_mtproto_history_message(
                            update=update,
                            project_id=project_id,
                            bot_id=bot_id,
                            sent_at=sent_at,
                            outgoing=bool(getattr(message, "out", False)),
                        )
                        await db.commit()
                    if result is not None:
                        imported_chat_id = result.chat_id
                        imported_messages += 1
                except Exception:
                    failed_messages += 1
                    logger.exception(
                        "MTProto initial history message failed bot_id=%s peer_id=%s "
                        "message_id=%s",
                        bot_id,
                        peer_id,
                        getattr(message, "id", None),
                    )

            if imported_chat_id is not None:
                async with get_db_session() as db:
                    await TelegramService(db).finalize_mtproto_history_dialog(
                        chat_id=imported_chat_id,
                        is_read=int(getattr(dialog, "unread_count", 0) or 0) == 0,
                    )
                    await db.commit()
                imported_dialogs += 1

        if attempted_messages and imported_messages == 0:
            raise RuntimeError(
                "Initial Telegram dialog synchronization could not persist any message"
            )
        if failed_messages:
            await send_operational_alert(
                component="telegram_account_worker",
                title="Telegram work account history was only partially synchronized",
                details={
                    "bot_id": bot_id,
                    "imported_dialogs": imported_dialogs,
                    "imported_messages": imported_messages,
                    "imported_media_bytes": imported_media_bytes,
                    "failed_messages": failed_messages,
                },
                dedupe_key=f"telegram-account-initial-sync-partial:{bot_id}",
            )
        logger.info(
            "MTProto initial dialog synchronization completed bot_id=%s dialogs=%s "
            "messages=%s media_bytes=%s failed=%s",
            bot_id,
            imported_dialogs,
            imported_messages,
            imported_media_bytes,
            failed_messages,
        )

    async def _sync_existing_outgoing(
        self,
        *,
        message: Any,
        peer_id: int,
        bot_id: UUID,
        project_id: UUID,
    ) -> bool:
        async with get_db_session() as db:
            service = TelegramService(db)
            chat = await service.chat_repo.get_by_external(
                project_id,
                str(peer_id),
                bot_id=bot_id,
            )
            if chat is None:
                await db.rollback()
                return False
            existing = await service.message_repo.get_by_external_id(
                chat.id,
                str(message.id),
            )
            if existing is None:
                await db.rollback()
                return False
            edit_date = getattr(message, "edit_date", None)
            if edit_date is not None:
                await service.handle_mtproto_message_edit(
                    external_chat_id=str(peer_id),
                    external_message_id=str(message.id),
                    project_id=project_id,
                    bot_id=bot_id,
                    text=str(getattr(message, "message", None) or ""),
                    is_caption=getattr(message, "media", None) is not None,
                    edited_at=edit_date,
                )
                await db.commit()
            else:
                await db.rollback()
            return True

    async def _load_sync_cursor(
        self,
        bot_id: UUID,
    ) -> tuple[datetime | None, int | None, bool]:
        async with get_db_session() as db:
            connection = await TelegramUserConnectionRepository(db).get_by_bot_id(bot_id)
            if connection is None:
                await db.rollback()
                return None, None, False
            last_synced_at = self._as_utc(connection.last_synced_at)
            telegram_user_id = connection.telegram_user_id
            initial_sync_required = connection.last_connected_at is None
            await db.rollback()
        return last_synced_at, telegram_user_id, initial_sync_required

    @staticmethod
    def _as_utc(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _is_supported_private_peer(peer: Any) -> bool:
        return bool(
            peer is not None
            and getattr(peer, "id", None) is not None
            and not bool(getattr(peer, "bot", False))
            and not bool(getattr(peer, "is_self", False))
        )

    @staticmethod
    def _local_media_bytes(update: TelegramUpdate) -> int:
        message = update.message
        if message is None:
            return 0
        media_items: list[Any] = list(message.photo or [])
        media_items.extend(
            item
            for item in (
                message.video,
                message.voice,
                message.video_note,
                message.document,
                message.audio,
                message.sticker,
                message.animation,
            )
            if item is not None
        )
        paths = {
            str(item.local_path)
            for item in media_items
            if getattr(item, "local_path", None)
        }
        return sum(
            os.path.getsize(path)
            for path in paths
            if os.path.isfile(path)
        )

    async def _download_media(
        self,
        *,
        client: TelegramClient,
        message: Any,
        bot_id: UUID,
        peer_id: int,
        max_bytes: int | None = None,
    ) -> str | None:
        if message.media is None:
            return None
        if max_bytes is not None and max_bytes <= 0:
            return None
        file_size = getattr(getattr(message, "file", None), "size", None)
        if (
            max_bytes is not None
            and isinstance(file_size, int)
            and file_size > max_bytes
        ):
            logger.info(
                "Skipping oversized MTProto history media bot_id=%s peer_id=%s "
                "message_id=%s bytes=%s limit=%s",
                bot_id,
                peer_id,
                getattr(message, "id", None),
                file_size,
                max_bytes,
            )
            return None
        directory = Path(settings.TELEGRAM_ACCOUNT_MEDIA_STORAGE_PATH) / str(bot_id) / str(peer_id)
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        extension = getattr(getattr(message, "file", None), "ext", None) or ".bin"
        target = directory / f"{message.id}{str(extension)[:16]}"
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        downloaded = await client.download_media(message, file=str(target))
        return str(downloaded) if downloaded else None

    @staticmethod
    def _message_schema(
        message: Any,
        *,
        chat: TelegramChat,
        peer_user: TelegramUser,
        local_path: str | None,
    ) -> TelegramMessage:
        file = getattr(message, "file", None)
        file_size = os.path.getsize(local_path) if local_path and os.path.exists(local_path) else None
        file_id = f"mtproto:{message.id}"
        common = {
            "file_id": file_id,
            "file_unique_id": file_id,
            "file_size": file_size,
            "local_path": local_path,
        }
        payload: dict[str, Any] = {
            "message_id": int(message.id),
            "text": message.message if message.media is None else None,
            "caption": message.message if message.media is not None else None,
            "chat": chat,
            "from_user": peer_user,
        }
        mime_type = getattr(file, "mime_type", None)
        file_name = getattr(file, "name", None)
        if getattr(message, "photo", None) is not None:
            payload["photo"] = [TelegramFile(**common)]
        elif getattr(message, "video_note", False):
            payload["video_note"] = TelegramFile(**common)
        elif getattr(message, "voice", False):
            payload["voice"] = TelegramVoice(**common, mime_type=mime_type)
        elif getattr(message, "video", False):
            payload["video"] = TelegramVideo(
                **common,
                mime_type=mime_type,
                file_name=file_name,
            )
        elif getattr(message, "audio", False):
            payload["audio"] = TelegramAudio(
                **common,
                mime_type=mime_type,
                file_name=file_name,
            )
        elif getattr(message, "sticker", False):
            payload["sticker"] = TelegramSticker(**common)
        elif getattr(message, "gif", False):
            payload["animation"] = TelegramDocument(
                **common,
                mime_type=mime_type,
                file_name=file_name,
            )
        elif message.media is not None:
            payload["document"] = TelegramDocument(
                **common,
                mime_type=mime_type,
                file_name=file_name,
            )
        reply_to_id = getattr(message, "reply_to_msg_id", None)
        if reply_to_id is not None:
            payload["reply_to_message"] = TelegramMessage(
                message_id=int(reply_to_id),
                chat=chat,
                from_user=peer_user,
            )
        return TelegramMessage(**payload)

    async def _consume_commands(self) -> None:
        redis = await get_redis()
        while not self._stopping.is_set():
            raw = await redis.brpoplpush(
                TELEGRAM_ACCOUNT_COMMAND_QUEUE,
                PROCESSING_QUEUE,
                timeout=1,
            )
            if raw is None:
                continue
            request_id = "unknown"
            try:
                command = json.loads(raw)
                request_id = str(command["request_id"])
                bot_id = UUID(str(command["bot_id"]))
                operation = str(command["operation"])
                expires_at = float(command.get("expires_at") or 0)
                if expires_at > 0 and time.time() >= expires_at:
                    raise TimeoutError("MTProto command expired before execution")
                payload = command.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("Command payload must be an object")
                result = await self._execute_command(bot_id, operation, payload)
                envelope = {"ok": True, "result": result}
            except Exception as exc:
                logger.exception("MTProto command failed request_id=%s", request_id)
                envelope = {
                    "ok": False,
                    "error": self._safe_error(exc),
                    "transient": self._is_transient(exc),
                }
            response_key = f"crm:telegram-account:response:{request_id}"
            await redis.rpush(response_key, json.dumps(envelope, ensure_ascii=True))
            await redis.expire(response_key, 120)
            await redis.lrem(PROCESSING_QUEUE, 1, raw)

    async def _execute_command(
        self,
        bot_id: UUID,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        client = self.clients.get(bot_id)
        if client is None or not client.is_connected():
            raise ConnectionError("Telegram work account is not connected")
        peer = await self._resolve_peer(client, bot_id, str(payload.get("external_chat_id") or ""))
        peer_id = int(payload.get("external_chat_id"))

        if operation == "send_message":
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("Outgoing MTProto text is empty")
            fingerprint = self._fingerprint(peer_id, text, "text")
            self._add_pending(bot_id, fingerprint)
            try:
                message = await client.send_message(
                    peer,
                    text,
                    reply_to=self._optional_int(payload.get("reply_to_message_id")),
                    parse_mode=None,
                )
            except Exception:
                self._discard_pending(bot_id, fingerprint)
                raise
            return self._sent_result(message, peer_id=peer_id, media_type="text")

        if operation == "send_media":
            path = Path(str(payload.get("path") or ""))
            if not path.is_file():
                raise FileNotFoundError("Outgoing MTProto media file is missing")
            media_type = str(payload.get("media_type") or "document")
            caption = str(payload.get("caption") or "").strip() or None
            fingerprint = self._fingerprint(peer_id, caption or "", media_type)
            self._add_pending(bot_id, fingerprint)
            try:
                message = await client.send_file(
                    peer,
                    file=str(path),
                    caption=caption,
                    force_document=media_type == "document",
                    voice_note=media_type == "voice",
                    video_note=media_type == "video_note",
                    supports_streaming=media_type in {"video", "video_note"},
                    reply_to=self._optional_int(payload.get("reply_to_message_id")),
                    parse_mode=None,
                )
            except Exception:
                self._discard_pending(bot_id, fingerprint)
                raise
            permanent_path = await self._preserve_outgoing_media(
                source=path,
                bot_id=bot_id,
                peer_id=peer_id,
                message_id=int(message.id),
            )
            return self._sent_result(
                message,
                peer_id=peer_id,
                media_type=media_type,
                local_path=permanent_path,
            )

        if operation in {"edit_message_text", "edit_message_caption"}:
            text = str(payload.get("text") or "").strip()
            message = await client.edit_message(
                peer,
                int(payload["message_id"]),
                text,
                parse_mode=None,
            )
            return self._sent_result(
                message,
                peer_id=peer_id,
                media_type="text" if operation.endswith("text") else "document",
            )

        if operation == "delete_message":
            result = await client.delete_messages(
                peer,
                [int(payload["message_id"])],
                revoke=True,
            )
            return {"deleted": bool(result)}

        if operation == "send_chat_action":
            action = self._chat_action(str(payload.get("action") or "typing"))
            await client(functions.messages.SetTypingRequest(peer=peer, action=action))
            return {"accepted": True}

        raise ValueError(f"Unsupported MTProto operation: {operation}")

    async def _resolve_peer(
        self,
        client: TelegramClient,
        bot_id: UUID,
        external_chat_id: str,
    ) -> Any:
        if not external_chat_id.lstrip("-").isdigit():
            raise ValueError("Telegram chat id is invalid")
        peer_id = int(external_chat_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(Chat.external_access_hash).where(
                    Chat.bot_id == bot_id,
                    Chat.external_chat_id == external_chat_id,
                    Chat.is_deleted.is_(False),
                    Chat.reset_at.is_(None),
                )
            )
            access_hash = result.scalar_one_or_none()
            await db.rollback()
        if access_hash is not None:
            return types.InputPeerUser(user_id=peer_id, access_hash=int(access_hash))
        try:
            return await client.get_input_entity(peer_id)
        except ValueError:
            await self._hydrate_dialog_entities(client, bot_id)
            try:
                return await client.get_input_entity(peer_id)
            except ValueError as retry_exc:
                raise RuntimeError(
                    "Telegram peer access hash is unavailable; wait for a new message from the user"
                ) from retry_exc

    async def _hydrate_dialog_entities(
        self,
        client: TelegramClient,
        bot_id: UUID,
    ) -> None:
        if bot_id in self.dialogs_hydrated:
            return
        async for _ in client.iter_dialogs(limit=None):
            pass
        self.dialogs_hydrated.add(bot_id)

    async def _load_connection(
        self,
        bot_id: UUID,
    ) -> tuple[int | None, UUID | None, str, str]:
        async with get_db_session() as db:
            connection = await TelegramUserConnectionRepository(db).get_by_bot_id(bot_id)
            if (
                connection is None
                or connection.auth_status != "authorized"
                or connection.bot is None
            ):
                await db.rollback()
                return None, None, "", ""
            api_id = connection.api_id
            project_id = connection.bot.project_id
            api_hash_encrypted = connection.api_hash_encrypted
            session_encrypted = connection.session_encrypted
            await db.rollback()
        api_hash = self.credentials.decrypt(api_hash_encrypted, label="API hash")
        session = self.credentials.decrypt(session_encrypted, label="authorization session")
        return api_id, project_id, api_hash, session

    async def _set_connection_state(
        self,
        bot_id: UUID,
        state: str,
        error: str | None,
    ) -> None:
        async with get_db_session() as db:
            values: dict[str, Any] = {
                "connection_status": state,
                "last_error": error,
            }
            if state == "connected":
                values["last_connected_at"] = datetime.now(timezone.utc)
            await TelegramUserConnectionRepository(db).update_by_bot_id(bot_id, **values)
            await db.commit()

    async def _mark_authorization_lost(self, bot_id: UUID) -> None:
        async with get_db_session() as db:
            await TelegramUserConnectionRepository(db).update_by_bot_id(
                bot_id,
                auth_status="error",
                connection_status="error",
                last_error="Telegram session is no longer authorized",
            )
            await db.commit()

    async def _touch_last_sync(self, bot_id: UUID) -> None:
        async with get_db_session() as db:
            await TelegramUserConnectionRepository(db).update_by_bot_id(
                bot_id,
                last_synced_at=datetime.now(timezone.utc),
            )
            await db.commit()

    @staticmethod
    async def _recover_interrupted_commands(redis: Any) -> None:
        while True:
            raw = await redis.rpoplpush(PROCESSING_QUEUE, TELEGRAM_ACCOUNT_COMMAND_QUEUE)
            if raw is None:
                return

    async def _preserve_outgoing_media(
        self,
        *,
        source: Path,
        bot_id: UUID,
        peer_id: int,
        message_id: int,
    ) -> str:
        directory = Path(settings.TELEGRAM_ACCOUNT_MEDIA_STORAGE_PATH) / str(bot_id) / str(peer_id)
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        suffix = source.suffix[:16] or ".bin"
        target = directory / f"{message_id}{suffix}"
        if source.resolve() != target.resolve():
            await asyncio.to_thread(shutil.copyfile, source, target)
            if source.parent.name == ".outbox":
                await asyncio.to_thread(source.unlink, missing_ok=True)
        return str(target)

    @staticmethod
    def _sent_result(
        message: Any,
        *,
        peer_id: int,
        media_type: str,
        local_path: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "message_id": int(message.id),
            "date": int(message.date.timestamp()) if message.date else None,
            "chat": {"id": peer_id, "type": "private"},
            "_transport": "user_mtproto",
        }
        if local_path:
            result["mtproto_media_path"] = local_path
        if media_type != "text":
            size = os.path.getsize(local_path) if local_path and os.path.exists(local_path) else None
            media_payload = {
                "file_id": f"mtproto:{message.id}",
                "file_unique_id": f"mtproto:{message.id}",
                "file_size": size,
            }
            result[media_type] = [media_payload] if media_type == "photo" else media_payload
        return result

    @staticmethod
    def _chat_action(value: str) -> Any:
        mapping = {
            "typing": types.SendMessageTypingAction,
            "record_voice": types.SendMessageRecordAudioAction,
            "record_video": types.SendMessageRecordVideoAction,
            "record_video_note": types.SendMessageRecordRoundAction,
            "upload_photo": lambda: types.SendMessageUploadPhotoAction(progress=0),
            "upload_video": lambda: types.SendMessageUploadVideoAction(progress=0),
            "upload_voice": lambda: types.SendMessageUploadAudioAction(progress=0),
            "upload_document": lambda: types.SendMessageUploadDocumentAction(progress=0),
            "upload_video_note": lambda: types.SendMessageUploadRoundAction(progress=0),
        }
        factory = mapping.get(value, types.SendMessageTypingAction)
        return factory()

    @staticmethod
    def _event_fingerprint(event: events.NewMessage.Event) -> str:
        message = event.message
        peer_id = TelegramAccountWorker._peer_id(event)
        media_type = TelegramAccountWorker._event_media_type(message)
        return TelegramAccountWorker._fingerprint(
            peer_id,
            str(message.message or "").strip(),
            media_type,
        )

    @staticmethod
    def _peer_id(event: Any) -> int:
        chat_id = event.chat_id
        if chat_id is None:
            raise RuntimeError("Telegram private peer id is unavailable")
        return int(chat_id)

    @staticmethod
    def _event_media_type(message: Any) -> str:
        if message.media is None:
            return "text"
        if getattr(message, "video_note", False):
            return "video_note"
        if getattr(message, "voice", False):
            return "voice"
        if getattr(message, "video", False):
            return "video"
        if getattr(message, "photo", None) is not None:
            return "photo"
        return "document"

    @staticmethod
    def _fingerprint(peer_id: int, text: str, media_type: str) -> str:
        return f"{peer_id}:{media_type}:{text}"

    def _add_pending(self, bot_id: UUID, fingerprint: str) -> None:
        pending = self.pending_crm_outgoing[bot_id]
        self._prune_pending(bot_id)
        pending.setdefault(fingerprint, []).append(time.monotonic())

    def _consume_pending(self, bot_id: UUID, fingerprint: str) -> bool:
        self._prune_pending(bot_id)
        pending = self.pending_crm_outgoing.get(bot_id)
        if not pending or not pending.get(fingerprint):
            return False
        pending[fingerprint].pop(0)
        if not pending[fingerprint]:
            pending.pop(fingerprint, None)
        return True

    def _discard_pending(self, bot_id: UUID, fingerprint: str) -> None:
        pending = self.pending_crm_outgoing.get(bot_id)
        if not pending or not pending.get(fingerprint):
            return
        pending[fingerprint].pop()
        if not pending[fingerprint]:
            pending.pop(fingerprint, None)

    def _prune_pending(self, bot_id: UUID) -> None:
        pending = self.pending_crm_outgoing.get(bot_id)
        if not pending:
            return
        cutoff = time.monotonic() - 120
        for fingerprint, timestamps in tuple(pending.items()):
            active = [timestamp for timestamp in timestamps if timestamp >= cutoff]
            if active:
                pending[fingerprint] = active
            else:
                pending.pop(fingerprint, None)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        return isinstance(exc, (ConnectionError, TimeoutError, FloodWaitError))

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, FloodWaitError):
            return f"Telegram rate limit: retry after {exc.seconds} seconds"
        if isinstance(exc, RPCError):
            return f"Telegram RPC error: {exc.__class__.__name__}"
        return f"{exc.__class__.__name__}: {' '.join(str(exc).split())[:500]}"


async def run_loop() -> None:
    logger.info("Starting Telegram MTProto account worker")
    await TelegramAccountWorker().run()
