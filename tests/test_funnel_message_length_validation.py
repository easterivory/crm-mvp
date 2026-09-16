from uuid import uuid4

import pytest

from app.schemas.funnel import FunnelGraphIn, FunnelStepIn
from app.services.funnel_block_registry import FunnelBlockRegistry
from app.services.funnel_service import FunnelService
from app.services.funnel_validator import FunnelGraphValidator


@pytest.mark.parametrize("kind,limit", [("photo", 1024), ("text", 4096)])
@pytest.mark.parametrize("legacy", [False, True])
def test_length_validation_preserves_drafts_and_identifies_message(kind, limit, legacy):
    item = {"type": kind, "text": "x" * (limit + 1)}
    if kind == "photo":
        item["telegram_file_id"] = "existing-file-id"
    step = FunnelStepIn(id=uuid4(), key="message", title="Offer", step_type="message",
                        block_type="generic_message", config_json=item if legacy else {"messages": [item]})
    graph = FunnelGraphIn(steps=[step])
    service = FunnelService.__new__(FunnelService)
    service.registry = FunnelBlockRegistry()
    service.graph_validator = FunnelGraphValidator()
    draft = service._validate_graph_payload(graph, strict_config=False)
    assert not any(issue.code == "telegram_text_too_long" for issue in draft.errors)
    published = service._validate_graph_payload(graph, strict_config=True)
    issue = next(issue for issue in published.errors if issue.code == "telegram_text_too_long")
    assert issue.step_id == step.id
    assert "Offer" in issue.message and str(limit) in issue.message
    item["text"] = "x" * limit
    step.config_json = item if legacy else {"messages": [item]}
    assert not any(issue.code == "telegram_text_too_long" for issue in
                   service._validate_graph_payload(graph, strict_config=True).errors)
    item["text"] = "{{first_name}}"
    step.config_json = item if legacy else {"messages": [item]}
    result = service._validate_graph_payload(graph, strict_config=True)
    assert any(issue.code == "telegram_dynamic_text_length" for issue in result.warnings)
    assert not any(issue.code == "telegram_text_too_long" for issue in result.errors)
