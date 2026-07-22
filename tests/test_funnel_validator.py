from app.services.funnel_validator import FunnelGraphValidator


def _node(
    node_id: str,
    *,
    step_type: str,
    title: str | None = None,
    config: dict | None = None,
) -> dict:
    return {
        "id": node_id,
        "title": title or node_id,
        "step_type": step_type,
        "block_type": f"generic_{step_type}",
        "config_json": config or {},
    }


def _edge(source: str, target: str) -> dict:
    return {"from_step_id": source, "to_step_id": target}


def test_backward_message_button_is_not_an_automatic_cycle() -> None:
    nodes = [
        _node("start", step_type="trigger"),
        _node("first", step_type="message"),
        _node(
            "second",
            step_type="message",
            config={
                "messages": [
                    {
                        "id": "message_1",
                        "text": "Вернуться назад?",
                        "buttons": [
                            {
                                "id": "back",
                                "label": "Назад",
                                "type": "branch",
                                "target_step_id": "first",
                            }
                        ],
                    }
                ]
            },
        ),
    ]
    edges = [
        _edge("start", "first"),
        _edge("first", "second"),
        _edge("second", "first"),
    ]

    result = FunnelGraphValidator().validate_graph(nodes, edges)

    assert result["is_valid"] is True
    assert not any("цикл" in error.lower() for error in result["errors"])


def test_legacy_top_level_backward_button_is_supported() -> None:
    nodes = [
        _node("start", step_type="trigger"),
        _node("question", step_type="input"),
        _node(
            "message",
            step_type="message",
            config={
                "text": "Изменить ответ?",
                "buttons": [
                    {
                        "id": "back",
                        "label": "Назад",
                        "type": "branch",
                        "target_step_id": "question",
                    }
                ],
            },
        ),
    ]
    edges = [
        _edge("start", "question"),
        _edge("question", "message"),
        _edge("message", "question"),
    ]

    result = FunnelGraphValidator().validate_graph(nodes, edges)

    assert result["is_valid"] is True


def test_automatic_cycle_is_still_rejected() -> None:
    nodes = [
        _node("start", step_type="trigger"),
        _node("condition", step_type="condition"),
        _node("action", step_type="action"),
    ]
    edges = [
        _edge("start", "condition"),
        _edge("condition", "action"),
        _edge("action", "condition"),
    ]

    result = FunnelGraphValidator().validate_graph(nodes, edges)

    assert result["is_valid"] is False
    assert any("автоматический цикл" in error.lower() for error in result["errors"])


def test_message_cycle_without_wait_or_buttons_is_still_rejected() -> None:
    nodes = [
        _node("start", step_type="trigger"),
        _node("first", step_type="message"),
        _node("second", step_type="message"),
    ]
    edges = [
        _edge("start", "first"),
        _edge("first", "second"),
        _edge("second", "first"),
    ]

    result = FunnelGraphValidator().validate_graph(nodes, edges)

    assert result["is_valid"] is False
    assert any("автоматический цикл" in error.lower() for error in result["errors"])
