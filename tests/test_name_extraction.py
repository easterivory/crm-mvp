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
    ("Бахти", "Бахти"), ("бахти", "бахти"),
    ("Бахтиёр", "Бахтиёр"), ("baxtiyor", "baxtiyor"),
    ("Бахти\nРустили билмайман", "Бахти"),
    ("Бахти Рустили билмайман", "Бахти"),
    ("Salom\nBaxti\nRus tili bilmayman", "Baxti"),
    ("Рустили билмайман", None), ("Рус тили билмайман", None),
    ("Рустили", None), ("bilmayman", None),
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


@pytest.mark.parametrize("config", [{"answer_type": "name"},
    {"answer_type": "text", "save_to": "first_name"}, {"answer_type": "text", "save_to": "name"}])
def test_uzbek_name_step_accepts_name_without_saving_language_message(config):
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    step = SimpleNamespace(block_type="generic_input", config_json=config)
    assert runtime._validate_input_answer(step, "Бахти") == {"valid": True, "normalized": "Бахти"}
    assert runtime._validate_input_answer(step, "Бахти\nРустили билмайман") == {"valid": True, "normalized": "Бахти"}
    assert runtime._validate_input_answer(step, "Рустили билмайман")["valid"] is False


@pytest.mark.parametrize("name", [
    "Санёк", "Лёха", "Серёга", "Димон", "Анютка", "Катюша", "Маруся", "Светик",
    "Надюша", "Тимоша", "Ярослава", "Демьян", "Андрюха", "Seryozha", "Yuliya", "Ksyusha",
    "Бахти", "Baxtiyor", "Жаҳонгир", "Jakhongir", "Шохрух", "Shoxrux", "Муҳаммад",
    "Muhammadali", "Абдурахмон", "Abdurakhmon", "Гўзал", "Go'zal", "Ўткир", "O‘tkir",
    "Oʼtkir", "O’tkir", "Нилуфар", "Nilufar", "Lutfullo", "Shahnoza",
    "Nacho", "Paco", "Pepe", "Lupita", "Toño", "Juampi", "Majo", "Mafer",
    "Matías", "Jazmín", "Caterina", "Guilherme", "Joãozinho", "Zezinho", "Pedrinho",
    "Marquinhos", "Rafinha", "Duduzinho", "Letícia", "Vinícius", "Heloísa", "Thaís",
])
@pytest.mark.parametrize("case", [str.lower, str.upper])
def test_expanded_names_recognized_without_cues_and_keep_original_spelling(name, case):
    answer = case(name)
    assert name_key(answer) in KNOWN_NAMES
    assert extract_answer_name(answer) == answer
    assert extract_answer_name(f"{answer}\n29") == answer


@pytest.mark.parametrize("text,expected", [
    ("Привет\nдимон\nмне 29 лет", "димон"),
    ("Salom\nshoxrux\nRus tili bilmayman", "shoxrux"),
    ("Hola\nnacho\ntengo 29 años", "nacho"),
    ("Olá\npedrinho\ntenho 30 anos", "pedrinho"),
    ("serёga\n123", None),
    ("спасибо\nне знаю", None), ("salom\nrahmat", None),
    ("hola\ngracias", None), ("olá\nobrigado", None),
    ("саша\nдимон", None), ("paco\nnacho", None),
    ("@pedrinho", None), ("nacho@example.com", None),
])
def test_expanded_dictionary_does_not_absorb_other_messages(text, expected):
    assert extract_answer_name(text) == expected


def test_dictionary_has_no_accidental_mixed_alphabet_tokens():
    import re

    assert not [name for name in KNOWN_NAMES
                if re.search(r"[a-z]", name) and re.search(r"[а-яё]", name)]


@pytest.mark.parametrize("answer,expected", [
    ("Арслан", "Арслан"), ("арслан", "арслан"), ("АРСЛАН", "АРСЛАН"),
    ("Арслан\n29", "Арслан"), ("Привет, меня зовут Арслан", "Арслан"),
    ("Не знаю\nарслан", "арслан"), ("Arslan\n29", "Arslan"),
    ("Мне нужна помощь", None), ("Денег нет", None),
    ("Hola necesito ayuda", None), ("I need help", None),
])
def test_vendored_dictionary_handles_reported_name_and_rejects_prose(answer, expected):
    assert extract_answer_name(answer) == expected


def test_external_dictionary_is_available_offline():
    assert len(KNOWN_NAMES) > 60000
    assert name_key("Арслан") in KNOWN_NAMES
