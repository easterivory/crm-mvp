from types import SimpleNamespace

import pytest

from app.services.funnel_runtime_service import FunnelRuntimeService


@pytest.mark.parametrize("config,expected", [
    ({"retry_message": "Пожалуйста, уточните имя\nБез фамилии"}, "Пожалуйста, уточните имя\nБез фамилии"),
    ({"retry_message": "Custom", "error_message": "Legacy"}, "Custom"),
    ({"error_message": "Legacy"}, "Legacy"),
    ({"validation": {"error_message": "Nested legacy"}}, "Nested legacy"),
    ({"retry_message": "  ", "error_message": "Legacy"}, "Legacy"),
    ({"retry_message": "Введите корректное значение"}, "Введите корректное значение"),
])
def test_explicit_fallback_preserved(config, expected):
    step = SimpleNamespace(config_json=config, block_type="generic_input")
    assert FunnelRuntimeService._input_retry_message(step) == expected


@pytest.mark.parametrize("config,block", [
    ({"answer_type": "name"}, "generic_input"),
    ({"answer_type": "text", "save_to": "first_name"}, "generic_input"),
    ({}, "ask_name"),
])
def test_name_default_requests_only_name(config, block):
    assert FunnelRuntimeService._input_retry_message(SimpleNamespace(config_json=config, block_type=block)) == (
        "Как я могу к вам обращаться? Напишите, пожалуйста, только имя."
    )


def test_empty_fallback_is_not_sent_as_empty_message():
    step = SimpleNamespace(config_json={"retry_message": " \n ", "answer_type": "number"}, block_type="generic_input")
    assert FunnelRuntimeService._input_retry_message(step) == "Не удалось разобрать ответ. Пожалуйста, напишите ещё раз."
