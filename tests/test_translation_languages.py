import asyncio

import pytest
from pydantic import ValidationError

from app.services.translation_languages import DEFAULT_LANGUAGES, TranslationLanguage
from app.services.translation_service import TranslationService, TranslationSettings, TranslationUnavailableError


def test_default_catalog_includes_previous_languages_and_uzbek():
    assert set(DEFAULT_LANGUAGES) == {"en", "ru", "es", "pt", "ar", "fr", "de", "it", "tr", "hi", "uz"}
    for code, label in DEFAULT_LANGUAGES.items():
        assert TranslationLanguage(value=code, label=label).value == code


@pytest.mark.parametrize("code,expected", [(" UZ ", "uz"), ("pt_BR", "pt-br"), ("zh-Hant", "zh-hant"), ("kk", "kk")])
def test_language_codes_normalized_and_extensible(code, expected):
    assert TranslationLanguage(value=code, label=" Language ").model_dump() == {"value": expected, "label": "Language"}


@pytest.mark.parametrize("code,label", [("", "Name"), ("uz", " "), ("<script>", "Name"), ("english", "Name"), ("abc-12345678", "Name")])
def test_invalid_languages_rejected(code, label):
    with pytest.raises(ValidationError):
        TranslationLanguage(value=code, label=label)


@pytest.mark.parametrize("provider", ["google", "deepl"])
def test_missing_provider_key_does_not_report_success(provider):
    # No DB or network is needed to reject a missing credential.
    service = TranslationService(None)
    translate = service._translate_google if provider == "google" else service._translate_deepl
    with pytest.raises(TranslationUnavailableError):
        asyncio.run(translate("Salom", "uz", "ru", TranslationSettings(provider, None, None)))
