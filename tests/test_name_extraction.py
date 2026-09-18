from types import SimpleNamespace

import pytest

from app.core.name_extraction import extract_answer_name, KNOWN_NAMES, name_key
from app.services.funnel_runtime_service import FunnelRuntimeService


@pytest.mark.parametrize("raw,expected", [
    ("Привет! Меня зовут Иван, мне 29 лет, живу в Москве", "Иван"),
    ("Привет\nИван\nМне 29 лет", "Иван"),
    ("Опыта нет\nАлишер\n29", "Алишер"),
    ("Иван Иванов", "Иван Иванов"),
    ("Меня зовут Редкослав Иванов, мне 29", "Редкослав Иванов"),
    ("Hola, me llamo José Luis, tengo 29 años", "José Luis"),
    ("María del Carmen", "María del Carmen"),
    ("Meu nome é João da Silva. Tenho 30 anos", "João da Silva"),
    ("Salom\nIsmim Otabek\n29 yoshdaman", "Otabek"),
    ("Азиз", "Азиз"), ("алёна", "алёна"), ("José", "José"),
    ("Анна-Мария", "Анна-Мария"),
    ("Мне 29 лет", None), ("Опыта нет", None), ("хочу начать", None),
    ("Иван\nПётр", None),
    ("Иван\nМария", None), ("123", None), ("@username", None),
    ("нормально", None), ("", None),
    ("Меня зовут не знаю", None), ("Имя: ааааа", None),
    ("Имя: @username", None),
    ("@José", None), ("Хорошо", None), ("ivan@Иван.ru", None),
])
def test_extract_answer_name(raw, expected):
    assert extract_answer_name(raw) == expected


@pytest.mark.parametrize("config", [{"answer_type": "name"}, {"answer_type": "text", "save_to": "name"},
                                     {"answer_type": "text", "save_to": "first_name"}])
def test_runtime_extracts_only_name_answers(config):
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    step = SimpleNamespace(block_type="generic_input", config_json=config)
    result = runtime._validate_input_answer(step, "Привет\nМеня зовут Иван, мне 29")
    assert result == {"valid": True, "normalized": "Иван"}
    assert not runtime._validate_input_answer(step, "Мне 29 лет")["valid"]
    step.config_json = {"answer_type": "text", "save_to": "comment"}
    assert runtime._validate_input_answer(step, "Привет, мне 29") == {"valid": True}


def test_name_dictionary_covers_requested_regions_and_accents():
    assert all(name_key(name) in KNOWN_NAMES for name in ("Алёна", "José", "João", "Алишер", "Otabek"))
