import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from fastapi import FastAPI, HTTPException
import httpx

from app.models.message import Message
from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageOut
from app.services.chat_service import ChatService
from app.services.telegram_service import TelegramService
from app.services.message_service import MessageService
from app.workers.telegram_account_worker import TelegramAccountWorker


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def stored_message(**changes) -> Message:
    values = dict(
        id=uuid4(), chat_id=uuid4(), external_message_id="123",
        message_type="text", sender_type="user", sender_id=None,
        body="First text", caption=None, edited_at=None, deleted_at=None,
        translated_text="Translation", original_text=None,
        raw_payload_json={"_transport": "user_mtproto", "mtproto_media_path": "/stored/photo.jpg"},
        created_at=datetime.now(timezone.utc), funnel_processed_at=datetime.now(timezone.utc),
    )
    values.update(changes)
    return Message(**values)


@pytest.mark.parametrize("caption", [False, True])
def test_edit_preserves_first_known_text_and_media_without_touching_funnel(caption: bool) -> None:
    message = stored_message(
        caption="First caption" if caption else None,
        message_type="photo" if caption else "text",
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: message)),
        flush=AsyncMock(),
    )
    repo = MessageRepository(db)
    processed_at = message.funnel_processed_at
    now = datetime.now(timezone.utc)

    async def run():
        for offset, text in [(0, "Second"), (1, "Third"), (1, "Third"), (-1, "Stale")]:
            await repo.mark_edited(
                message_id=message.id, text=text, is_caption=caption,
                edited_at=now + timedelta(seconds=offset), preserve_previous=True,
            )

    asyncio.run(run())
    assert getattr(message, "caption" if caption else "body") == "Third"
    assert message.text_before_edit == ("First caption" if caption else "First text")
    assert message.raw_payload_json["mtproto_media_path"] == "/stored/photo.jpg"
    assert message.translated_text is None
    assert message.original_text is None
    assert message.funnel_processed_at == processed_at
    assert message.edited_at == now + timedelta(seconds=1)
    assert "FOR UPDATE" in sql(db.execute.await_args_list[0].args[0])
    assert MessageOut.model_validate(message).text_before_edit == message.text_before_edit


def test_edit_replay_does_not_clear_fresh_translation_or_invent_original() -> None:
    now = datetime.now(timezone.utc)
    message = stored_message(edited_at=now)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: message)),
        flush=AsyncMock(),
    )
    asyncio.run(MessageRepository(db).mark_edited(
        message_id=message.id, text=message.body, is_caption=False,
        edited_at=now, preserve_previous=True,
    ))
    assert message.text_before_edit is None
    assert message.translated_text == "Translation"


def test_edit_after_delete_does_not_resurrect_message() -> None:
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
        flush=AsyncMock(),
    )
    asyncio.run(MessageRepository(db).mark_edited(
        message_id=uuid4(), text="Changed", is_caption=False,
        edited_at=datetime.now(timezone.utc), preserve_previous=True,
    ))
    assert "messages.deleted_at IS NULL" in sql(db.execute.await_args.args[0])
    db.flush.assert_not_awaited()


def test_bot_edit_retains_existing_update_path() -> None:
    db = SimpleNamespace(execute=AsyncMock())
    asyncio.run(MessageRepository(db).mark_edited(
        message_id=uuid4(), text="Changed", is_caption=False,
        edited_at=datetime.now(timezone.utc),
    ))
    statement = sql(db.execute.await_args.args[0])
    assert statement.startswith("UPDATE messages SET")
    assert "raw_payload_json" not in statement


def test_deleted_history_is_visible_only_for_the_owning_user_account() -> None:
    statement = sql(select(Message.id).where(MessageRepository.history_visibility_expr()))
    assert "messages.deleted_at IS NULL OR (EXISTS" in statement
    assert "bots.id = chats.bot_id" in statement
    assert "chats.id = messages.chat_id" in statement
    assert "bots.transport_type = 'user_mtproto'" in statement


def test_history_count_page_and_deleted_cursor_share_visibility_and_cycle_boundary() -> None:
    now, chat_id, anchor_id = datetime.now(timezone.utc), uuid4(), uuid4()
    anchor = SimpleNamespace(created_at=now, id=anchor_id)
    results = [
        SimpleNamespace(one_or_none=lambda: anchor),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
        SimpleNamespace(scalar_one=lambda: 1),
    ]
    db = SimpleNamespace(execute=AsyncMock(side_effect=results))
    repo = MessageRepository(db)

    async def run():
        await repo.list_by_chat(
            chat_id, since=now, before_message_id=anchor_id, offset=100,
            include_account_tombstones=True,
        )
        assert await repo.count_by_chat(chat_id, since=now, include_account_tombstones=True) == 1

    asyncio.run(run())
    statements = [sql(call.args[0]) for call in db.execute.await_args_list]
    for statement in statements:
        assert "bots.transport_type = 'user_mtproto'" in statement
        assert str(chat_id) in statement
    assert "messages.created_at >=" in statements[1]
    assert "messages.created_at >=" in statements[2]
    assert " OFFSET " not in statements[1]


def test_runtime_and_ai_history_still_excludes_deleted_messages_by_default() -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )))
    asyncio.run(MessageRepository(db).list_by_chat(uuid4()))
    statement = sql(db.execute.await_args.args[0])
    assert "messages.deleted_at IS NULL" in statement
    assert "user_mtproto" not in statement


def test_chat_preview_and_search_keep_account_tombstones() -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )))
    repo = ChatRepository(db)

    async def run():
        await repo.latest_messages_for_chats([uuid4()])
        await repo.search_hit_messages_for_chats([uuid4()], "text")

    asyncio.run(run())
    for call in db.execute.await_args_list:
        statement = sql(call.args[0])
        assert "bots.transport_type = 'user_mtproto'" in statement
        assert "chats.reset_at IS NULL" in statement
    message = stored_message(deleted_at=datetime.now(timezone.utc))
    preview = ChatService._message_preview_context(message, prefix="last_message")
    assert preview["last_message_deleted_at"] == message.deleted_at
    assert preview["last_message_text"] == "First text"


@pytest.mark.parametrize("processed,deleted,outgoing", [
    (True, False, False), (False, False, False), (False, True, False), (False, False, True),
])
def test_recovery_syncs_incoming_edits_without_replaying_processed_input(processed, deleted, outgoing) -> None:
    now, project_id, bot_id = datetime.now(timezone.utc), uuid4(), uuid4()
    message = stored_message(
        funnel_processed_at=now if processed else None,
        deleted_at=now if deleted else None,
    )
    db = AsyncMock()
    db.__aenter__.return_value = db
    service = SimpleNamespace(
        chat_repo=SimpleNamespace(get_by_external=AsyncMock(return_value=SimpleNamespace(id=message.chat_id))),
        message_repo=SimpleNamespace(get_by_external_id=AsyncMock(return_value=message)),
        handle_mtproto_message_edit=AsyncMock(),
    )
    worker = TelegramAccountWorker.__new__(TelegramAccountWorker)
    with patch("app.workers.telegram_account_worker.get_db_session", return_value=db), patch(
        "app.workers.telegram_account_worker.TelegramService", return_value=service,
    ):
        result = asyncio.run(worker._sync_existing_message(
            message=SimpleNamespace(id=123, out=outgoing, edit_date=now, message="Updated", media=None),
            peer_id=321, bot_id=bot_id, project_id=project_id,
        ))
    assert result is (processed or deleted or outgoing)
    service.handle_mtproto_message_edit.assert_awaited_once()
    service.chat_repo.get_by_external.assert_awaited_once_with(project_id, "321", bot_id=bot_id)


def test_mtproto_delete_is_scoped_and_only_marks_rows() -> None:
    service = TelegramService.__new__(TelegramService)
    bot_id, project_id, now = uuid4(), uuid4(), datetime.now(timezone.utc)
    message = stored_message()
    service.chat_repo = SimpleNamespace(get_by_external=AsyncMock(return_value=SimpleNamespace(id=message.chat_id)))
    service.message_repo = SimpleNamespace(
        get_by_external_id=AsyncMock(return_value=message), mark_deleted=AsyncMock(),
    )
    count = asyncio.run(service.handle_mtproto_message_delete(
        external_chat_id="321", external_message_ids=["123"],
        project_id=project_id, bot_id=bot_id, deleted_at=now,
    ))
    assert count == 1
    service.chat_repo.get_by_external.assert_awaited_once_with(project_id, "321", bot_id=bot_id)
    service.message_repo.mark_deleted.assert_awaited_once_with(message_id=message.id, deleted_at=now)
    assert message.body == "First text"


def test_soft_delete_retains_content_and_is_idempotent() -> None:
    db = SimpleNamespace(execute=AsyncMock())
    asyncio.run(MessageRepository(db).mark_deleted(message_id=uuid4(), deleted_at=datetime.now(timezone.utc)))
    statement = sql(db.execute.await_args.args[0])
    assert statement.startswith("UPDATE messages SET")
    assert "deleted_at IS NULL" in statement
    for field in ["body=", "caption=", "raw_payload_json=", "funnel_processed_at="]:
        assert field not in statement


def test_link_preview_edit_updates_text_body_not_hidden_caption() -> None:
    message = stored_message()
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: message)),
        flush=AsyncMock(),
    )
    asyncio.run(MessageRepository(db).mark_edited(
        message_id=message.id, text="https://example.com", is_caption=True,
        edited_at=datetime.now(timezone.utc), preserve_previous=True,
    ))
    assert message.body == "https://example.com"
    assert message.caption is None


def test_visible_history_refresh_is_scoped_to_chat_and_current_cycle() -> None:
    chat_id, message_id, now = uuid4(), uuid4(), datetime.now(timezone.utc)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )))
    asyncio.run(MessageRepository(db).list_history_by_ids(
        chat_id=chat_id, message_ids=[message_id], since=now,
    ))
    statement = sql(db.execute.await_args.args[0])
    assert str(chat_id) in statement and str(message_id) in statement
    assert "messages.created_at >=" in statement
    assert "bots.transport_type = 'user_mtproto'" in statement


def test_visible_history_refresh_checks_project_before_loading_rows() -> None:
    service = MessageService.__new__(MessageService)
    service.chat_repo = SimpleNamespace(get_active=AsyncMock(return_value=None))
    service.message_repo = SimpleNamespace(list_history_by_ids=AsyncMock())
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.refresh_history_messages(
            chat_id=uuid4(), project_id=uuid4(), message_ids=[uuid4()],
        ))
    assert error.value.status_code == 404
    service.message_repo.list_history_by_ids.assert_not_awaited()


def test_history_refresh_route_limits_batch_and_validates_ids() -> None:
    from app.api.v1.routers.messages import router, get_current_project_id, get_db

    project_id, chat_id, message_id = uuid4(), uuid4(), uuid4()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_project_id] = lambda: project_id
    app.dependency_overrides[get_db] = lambda: None
    service = SimpleNamespace(refresh_history_messages=AsyncMock(return_value=[]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = f"/chats/{chat_id}/messages/history-refresh"
            assert (await client.get(url, params={"message_ids": str(message_id)})).status_code == 200
            assert (await client.get(url, params={"message_ids": "invalid"})).status_code == 422
            assert (await client.get(url)).status_code == 422
            assert (await client.get(url, params=[("message_ids", str(message_id))] * 101)).status_code == 422

    with patch("app.api.v1.routers.messages.MessageService", return_value=service):
        asyncio.run(run())
    service.refresh_history_messages.assert_awaited_once_with(
        chat_id=chat_id, project_id=project_id, message_ids=[message_id],
    )
