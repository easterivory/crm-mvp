import asyncio
import importlib.util
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.lander import ProjectDomain
from app.schemas.funnel import FunnelPushRuleIn
from app.schemas.funnel import FunnelGraphIn
from app.services.funnel_service import FunnelService
from fastapi import HTTPException
from app.schemas.lander import ProjectDomainCreate
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.lander_admin_service import LanderAdminService


def test_push_photo_is_optional_and_caption_is_validated():
    base = {"step_id": uuid4(), "delay_minutes": 30}
    assert FunnelPushRuleIn(**base, message_text="Legacy push").photo_upload_id is None
    assert FunnelPushRuleIn(**base, photo_upload_id=uuid4()).message_text == ""
    with pytest.raises(ValidationError):
        FunnelPushRuleIn(**base)
    with pytest.raises(ValidationError):
        FunnelPushRuleIn(**base, photo_upload_id=uuid4(), message_text="x" * 1025)


@pytest.mark.parametrize("photo", [None, uuid4()])
def test_push_sends_photo_through_existing_media_pipeline_and_deduplicates(photo):
    chat_id, step_id, rule_id = uuid4(), uuid4(), uuid4()
    state = SimpleNamespace(current_step_id=step_id, completed_at=None, is_paused=False,
                            waiting_for_answer=True, runtime_json={}, entered_step_at=datetime.now(timezone.utc))
    rule = SimpleNamespace(id=rule_id, step_id=step_id, is_active=True, message_text="Reminder",
                           photo_upload_id=photo, action_after_send="stay")
    service = FunnelRuntimeService.__new__(FunnelRuntimeService)
    service.repo = SimpleNamespace(lock_chat_for_runtime=AsyncMock(return_value=True),
        get_chat_funnel_state=AsyncMock(return_value=state), get_push_rule=AsyncMock(return_value=rule),
        update_chat_funnel_runtime=AsyncMock())
    service.chat_repo = SimpleNamespace(increment_unanswered_push_count=AsyncMock())
    service._create_outgoing_message = AsyncMock()
    assert asyncio.run(service.mark_push_sent(chat_id=chat_id, push_rule_id=rule_id))
    args = service._create_outgoing_message.await_args.kwargs
    assert args["text"] == "Reminder"
    if photo:
        assert args["message_type"] == "photo" and args["broadcast_upload_id"] == photo
    else:
        assert "broadcast_upload_id" not in args
    state.runtime_json = service.repo.update_chat_funnel_runtime.await_args.kwargs["runtime_json"]
    assert not asyncio.run(service.mark_push_sent(chat_id=chat_id, push_rule_id=rule_id))
    service._create_outgoing_message.assert_awaited_once()


@pytest.mark.parametrize("target", [None, uuid4()])
def test_inline_button_respects_target_or_continues_remaining_messages(target):
    service = FunnelRuntimeService.__new__(FunnelRuntimeService)
    step = SimpleNamespace(id=uuid4(), step_type="message", block_type="generic_message", config_json={
        "messages": [{"text": "First", "buttons": [{"label": "Next", "value": "next", "target_step_id": target}]},
                     {"text": "Second", "wait_for_answer": True}],
    })
    state = SimpleNamespace(current_step_id=step.id, funnel_id=uuid4(), funnel_version_id=uuid4(),
        is_paused=False, completed_at=None, entered_step_at=None,
        runtime_json={"message_sequence": {"step_id": str(step.id), "message_index": 0}})
    service.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state),
        get_step=AsyncMock(return_value=step), upsert_chat_funnel_state=AsyncMock())
    service._execute_message_sequence = AsyncMock(return_value=step)
    service._move_to_step_id = AsyncMock(return_value=SimpleNamespace(id=target))
    service._execute_from_step = AsyncMock()
    service._move_from_step = AsyncMock()
    asyncio.run(service.process_incoming_button(chat_id=uuid4(), callback_data=f"fr:{step.id.hex}:0:0"))
    if target:
        assert service._move_to_step_id.await_args.kwargs["target_step_id"] == target
        service._execute_from_step.assert_awaited_once()
        service._execute_message_sequence.assert_not_awaited()
    else:
        assert service._execute_message_sequence.await_args.kwargs["start_index"] == 1
        service._execute_from_step.assert_not_awaited()
        service._move_from_step.assert_not_awaited()


def test_legacy_options_buttons_are_available():
    service = FunnelRuntimeService.__new__(FunnelRuntimeService)
    buttons = service._buttons_from_step(SimpleNamespace(config_json={"options": ["Yes", "No"]}))
    assert [item["value"] for item in buttons] == ["Yes", "No"]


def test_push_photo_from_another_project_is_rejected_before_graph_replacement():
    service = FunnelService.__new__(FunnelService)
    service._ensure_write_allowed = lambda actor: None
    service._get_version_or_404 = AsyncMock(return_value=SimpleNamespace(status="draft"))
    service.db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []))))
    service.repo = SimpleNamespace(replace_graph=AsyncMock())
    project_id = uuid4()
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.save_graph(funnel_id=uuid4(), version_id=uuid4(), project_id=project_id,
            current_user=SimpleNamespace(), graph=FunnelGraphIn(push_rules=[FunnelPushRuleIn(
                step_id=uuid4(), delay_minutes=30, photo_upload_id=uuid4())])))
    assert error.value.status_code == 422
    service.repo.replace_graph.assert_not_awaited()
    statement = service.db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert project_id in statement.params.values()
    assert "expires_at IS NULL" in str(statement)


def test_domain_lookup_is_project_scoped_and_can_reactivate_only_own_binding():
    project_id = uuid4()
    domain = ProjectDomain(id=uuid4(), project_id=project_id, domain_name="promo.example.com",
        is_active=False, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: domain)),
                         flush=AsyncMock(), refresh=AsyncMock())
    service = LanderAdminService(db)
    service._ensure_admin_project_access = AsyncMock()
    asyncio.run(service.create_domain(project_id=project_id, data=ProjectDomainCreate(domain_name=domain.domain_name), actor=SimpleNamespace()))
    statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "project_domains.project_id =" in str(statement)
    assert project_id in statement.params.values()
    assert domain.is_active
    unique = [index for index in ProjectDomain.__table__.indexes if index.unique]
    assert [column.name for column in unique[0].columns] == ["project_id", "domain_name"]


def test_migration_sql_preserves_old_rows_and_refuses_lossy_downgrade():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260916_0077_push_photos_shared_domains.py"
    spec = importlib.util.spec_from_file_location("migration_0077", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
        module.downgrade()
    script = output.getvalue()
    assert "ADD COLUMN photo_upload_id UUID" in script
    assert "(project_id, domain_name)" in script
    assert "RAISE EXCEPTION" in script
    assert "DELETE FROM" not in script
