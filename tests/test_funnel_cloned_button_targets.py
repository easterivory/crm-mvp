import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models.funnel import FunnelStep
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_runtime_service import FunnelRuntimeService


def test_clone_remaps_nested_targets_without_modifying_source():
    first, second = uuid4(), uuid4()
    config = {"messages": [{"id": "msg", "buttons": [{"id": "button",
              "target_step_id": str(second), "value": "same"}]}],
              "timeout_target_step_id": str(first), "text": str(second)}
    source = [SimpleNamespace(id=identifier, key=str(identifier), title="Step", step_type="message",
              block_type="generic_message", position_x=0, position_y=0,
              config_json=config if identifier == first else {}, validation_json=None,
              ui_schema_json=None) for identifier in (first, second)]
    repo = FunnelRepository.__new__(FunnelRepository)
    repo.db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    repo.list_steps = AsyncMock(return_value=source)
    repo.list_edges = AsyncMock(return_value=[])
    repo.list_push_rules = AsyncMock(return_value=[])
    repo.list_field_mappings = AsyncMock(return_value=[])
    asyncio.run(repo.clone_graph(uuid4(), uuid4()))
    clones = [call.args[0] for call in repo.db.add.call_args_list if isinstance(call.args[0], FunnelStep)]
    assert clones[0].config_json["messages"][0]["buttons"][0]["target_step_id"] == str(clones[1].id)
    assert clones[0].config_json["timeout_target_step_id"] == str(clones[0].id)
    assert clones[0].config_json["text"] == str(second)
    assert config["messages"][0]["buttons"][0]["target_step_id"] == str(second)


@pytest.mark.parametrize("index", range(4))
def test_callback_uses_exact_saved_edge_even_with_duplicate_button_values(index):
    step_id, version = uuid4(), uuid4()
    targets = [uuid4() for _ in range(4)]
    buttons = [{"id": f"b{i}", "label": f"Amount {i}", "value": "button"} for i in range(4)]
    step = SimpleNamespace(id=step_id, step_type="message", block_type="generic_message",
                           config_json={"messages": [{"id": "m1", "text": "Choose", "buttons": buttons}]})
    state = SimpleNamespace(current_step_id=step_id, funnel_id=uuid4(), funnel_version_id=version,
                            is_paused=False, completed_at=None, entered_step_at=None,
                            runtime_json={"message_sequence": {"step_id": str(step_id), "message_index": 0}})
    edges = [SimpleNamespace(from_step_id=step_id, to_step_id=targets[i],
             condition_json={"source_key": f"message:m1:button:b{i}"}) for i in range(4)]
    service = FunnelRuntimeService.__new__(FunnelRuntimeService)
    service.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state),
        get_step=AsyncMock(return_value=step), list_edges=AsyncMock(return_value=edges),
        upsert_chat_funnel_state=AsyncMock())
    service._move_to_step_id = AsyncMock(return_value=None)
    service._execute_message_sequence = AsyncMock()
    asyncio.run(service.process_incoming_button(chat_id=uuid4(), callback_data=f"fr:{step_id.hex}:0:{index}"))
    assert service._move_to_step_id.await_args.kwargs["target_step_id"] == str(targets[index])
    service._execute_message_sequence.assert_not_awaited()
