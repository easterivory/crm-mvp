import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.telegram import TelegramUpdate
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.telegram_service import TelegramService


@pytest.mark.parametrize("custom,expected", [(None, "Занять место"), ("Хочу участвовать", "Хочу участвовать"), ("  ", "Занять место")])
def test_query_markup_and_answer_matching(custom, expected):
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    buttons = runtime._normalize_buttons([{"id": "q1", "label": "Занять место", "type": "query", "query_text": custom}])
    markup = runtime._reply_markup_for_buttons(step=SimpleNamespace(id=uuid4()), buttons=buttons, button_mode="reply")
    assert markup == {"inline_keyboard": [[{"text": "Занять место", "switch_inline_query_current_chat": expected}]]}
    assert runtime._choice_for_query_buttons(buttons, expected) == buttons[0]
    assert runtime._choice_for_query_buttons(buttons, f"@Example_bot {expected}") == buttons[0]
    assert runtime._choice_for_query_buttons(buttons, "unrelated") is None


@pytest.mark.parametrize("known", [True, False])
def test_inline_query_offers_result_without_advancing_or_creating_chat(known):
    service = TelegramService.__new__(TelegramService)
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    service.funnel_runtime = runtime
    step = SimpleNamespace(id=uuid4(), config_json={"messages": [{"id": "m", "buttons": [
        {"id": "q", "type": "query", "label": "Join"}]}]})
    state = SimpleNamespace(waiting_for_answer=True, is_paused=False, completed_at=None,
        current_step_id=step.id, runtime_json={"message_sequence": {"step_id": str(step.id), "message_index": 0}})
    runtime.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state), get_step=AsyncMock(return_value=step))
    chat = SimpleNamespace(id=uuid4(), is_blocked=False, is_deleted=False, reset_at=None)
    service.chat_repo = SimpleNamespace(get_by_external=AsyncMock(return_value=chat if known else None))
    service.bot_repo = SimpleNamespace(get_bot_token_by_id=AsyncMock(return_value="test-token"))
    service.telegram_sender = SimpleNamespace(answer_inline_query=AsyncMock())
    service.db = SimpleNamespace(commit=AsyncMock())
    update = TelegramUpdate.model_validate({"update_id": 1, "inline_query": {
        "id": "123", "from": {"id": 42, "is_bot": False, "first_name": "Test"}, "query": "Join", "offset": ""}})
    asyncio.run(service.handle_update(update, project_id=uuid4(), bot_id=uuid4()))
    results = service.telegram_sender.answer_inline_query.await_args.args[2]
    assert bool(results) is known
    if known:
        assert results[0]["input_message_content"] == {"message_text": "Join"}


def test_duplicate_query_text_is_ambiguous_not_first_button():
    buttons = [{"type": "query", "label": "Join", "target_step_id": str(uuid4())} for _ in range(2)]
    assert FunnelRuntimeService._choice_for_query_buttons(buttons, "Join") is None


@pytest.mark.parametrize("answer", ["Join", "@Example_bot Join"])
def test_real_message_from_query_continues_its_own_branch(answer):
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    target = str(uuid4())
    step = SimpleNamespace(id=uuid4(), step_type="message", block_type="generic_message",
        config_json={"messages": [{"id": "m1", "buttons": [
            {"id": "other", "type": "branch", "label": "Other", "target_step_id": str(uuid4())},
            {"id": "q", "type": "query", "label": "Join", "target_step_id": target}]}]})
    state = SimpleNamespace(current_step_id=step.id, funnel_id=uuid4(), funnel_version_id=uuid4(),
        is_paused=False, completed_at=None, waiting_for_answer=True, entered_step_at=None,
        runtime_json={"message_sequence": {"step_id": str(step.id), "message_index": 0}})
    runtime.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state),
        get_step=AsyncMock(return_value=step), upsert_chat_funnel_state=AsyncMock())
    runtime.apply_field_mappings = AsyncMock()
    runtime._log_step_event = AsyncMock()
    runtime._move_to_step_id = AsyncMock(return_value=None)
    assert asyncio.run(runtime.process_incoming_message(chat_id=uuid4(), text=answer))
    assert runtime._move_to_step_id.await_args.kwargs["target_step_id"] == target
    assert runtime.apply_field_mappings.await_args.kwargs["answer"] == "Join"
