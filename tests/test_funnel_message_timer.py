import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.funnel import FunnelGraphIn, FunnelStepIn
from app.services.funnel_block_registry import FunnelBlockRegistry
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.funnel_service import FunnelService
from app.services.funnel_validator import FunnelGraphValidator


def timer_step(**config):
    return SimpleNamespace(id=uuid4(), step_type="message", block_type="generic_message",
        config_json={"text": "Welcome", "auto_advance_enabled": True,
                     "auto_advance_seconds": 20, "timeout_target_step_id": str(uuid4()), **config})


@pytest.mark.parametrize("config,seconds", [({}, 20), ({"auto_advance_enabled": False}, 0),
    ({"auto_advance_enabled": None}, 0), ({"auto_advance_seconds": 0}, 0),
    ({"auto_advance_seconds": True}, 0), ({"auto_advance_seconds": 1.5}, 0),
    ({"auto_advance_seconds": 604801}, 0), ({"timeout_target_step_id": ""}, 0)])
def test_timer_opt_in_and_bounds(config, seconds):
    assert FunnelRuntimeService._message_auto_advance_seconds(timer_step(**config)) == seconds
    assert FunnelRuntimeService._message_auto_advance_seconds(SimpleNamespace(config_json={})) == 0


@pytest.mark.parametrize("enabled", [False, True])
def test_timer_is_scheduled_only_after_message_delivery(enabled):
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    step = timer_step(auto_advance_enabled=enabled)
    state = SimpleNamespace(funnel_id=uuid4(), funnel_version_id=uuid4(), entered_step_at=None, runtime_json={})
    runtime.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state), upsert_chat_funnel_state=AsyncMock())
    runtime._send_message_item = AsyncMock(return_value=True)
    runtime._schedule_job = AsyncMock()
    runtime._move_from_step = AsyncMock()
    asyncio.run(runtime._execute_message_sequence(chat_id=uuid4(), step=step))
    runtime._send_message_item.assert_awaited_once()
    if enabled:
        scheduled = runtime._schedule_job.await_args.kwargs
        saved = runtime.repo.upsert_chat_funnel_state.await_args.kwargs
        assert scheduled["job_type"] == "message_auto_advance"
        assert scheduled["delay_seconds"] == 20
        assert saved["waiting_for_answer"] is True
        assert scheduled["payload_json"] == saved["runtime_json"]["message_auto_advance"]
        runtime._move_from_step.assert_not_awaited()
    else:
        runtime._schedule_job.assert_not_awaited()
        runtime._move_from_step.assert_awaited_once()


@pytest.mark.parametrize("stale", [None, "answered", "new_wait", "paused", "completed", "moved"])
def test_timer_consumed_once_and_stale_tasks_do_not_move_funnel(stale):
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    step = timer_step()
    marker = {"token": str(uuid4()), "message_index": 0}
    state = SimpleNamespace(funnel_id=uuid4(), funnel_version_id=uuid4(), entered_step_at=None,
        current_step_id=step.id, completed_at=None, is_paused=False, waiting_for_answer=True,
        runtime_json={"message_auto_advance": marker})
    job = SimpleNamespace(id=uuid4(), chat_id=uuid4(), step_id=step.id,
        funnel_version_id=state.funnel_version_id, job_type="message_auto_advance", payload_json=marker)
    if stale == "answered":
        state.runtime_json = runtime._runtime_with_answer(state.runtime_json, step_id=step.id, answer="Join")
    elif stale == "new_wait":
        state.runtime_json = {"message_auto_advance": {"token": str(uuid4()), "message_index": 0}}
    elif stale == "paused":
        state.is_paused = True
    elif stale == "completed":
        state.completed_at = "completed"
    elif stale == "moved":
        state.current_step_id = uuid4()

    async def save(**values):
        state.runtime_json = values["runtime_json"]
        state.waiting_for_answer = values["waiting_for_answer"]

    runtime.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state),
        get_step=AsyncMock(return_value=step), upsert_chat_funnel_state=AsyncMock(side_effect=save))
    runtime._move_to_step_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    runtime._execute_from_step = AsyncMock()
    asyncio.run(runtime.process_scheduled_job(job))
    asyncio.run(runtime.process_scheduled_job(job))
    assert runtime._move_to_step_id.await_count == (0 if stale else 1)
    assert runtime._execute_from_step.await_count == (0 if stale else 1)
    if not stale:
        assert runtime._move_to_step_id.await_args.kwargs["target_step_id"] == step.config_json["timeout_target_step_id"]


def test_answer_never_uses_timer_edge_as_default():
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    step = timer_step()
    timer_edge = SimpleNamespace(id=uuid4(), from_step_id=step.id, condition_json={"source_key": "message:timeout"})
    next_edge = SimpleNamespace(id=uuid4(), from_step_id=step.id, condition_json={"source_key": "message:next"})
    runtime.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=SimpleNamespace(funnel_version_id=uuid4())),
        list_edges=AsyncMock(return_value=[timer_edge, next_edge]))
    runtime.move_to_next_step = AsyncMock()
    asyncio.run(runtime._move_from_step(chat_id=uuid4(), step=step, answer="hello"))
    assert runtime.move_to_next_step.await_args.kwargs["edge_id"] == next_edge.id


def test_invalid_timer_can_be_drafted_but_not_published():
    step = FunnelStepIn(id=uuid4(), key="welcome", title="Welcome", step_type="message",
        block_type="generic_message", config_json={"text": "Hi", "auto_advance_enabled": True, "auto_advance_seconds": -1})
    service = FunnelService.__new__(FunnelService)
    service.registry = FunnelBlockRegistry()
    service.graph_validator = FunnelGraphValidator()
    graph = FunnelGraphIn(steps=[step])
    codes = {"invalid_message_timer", "missing_message_timer_target"}
    assert not codes.intersection(issue.code for issue in service._validate_graph_payload(graph, strict_config=False).errors)
    assert codes.issubset(issue.code for issue in service._validate_graph_payload(graph, strict_config=True).errors)


def test_query_response_clears_only_timer_not_saved_answers():
    step_id = uuid4()
    runtime = FunnelRuntimeService._runtime_with_answer(
        {"message_auto_advance": {"token": "pending"}, "previous_data": {"name": "Test"}},
        step_id=step_id, answer="Join", button={"id": "query", "label": "Join"},
    )
    assert "message_auto_advance" not in runtime
    assert runtime["previous_data"] == {"name": "Test"}
    assert runtime["last_answer"] == "Join"
    assert runtime["last_button"]["id"] == "query"


def test_valid_timer_is_a_runtime_boundary_but_disabled_timer_is_not():
    validator = FunnelGraphValidator()
    node = SimpleNamespace(kind="message", config=timer_step().config_json)
    assert validator._is_runtime_boundary(node)
    node.config["auto_advance_enabled"] = False
    assert not validator._is_runtime_boundary(node)
