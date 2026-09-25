"""Shared, extensible UI language catalog. Provider support is independent."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator

from app.services.system_setting_service import SystemSettingService

LANGUAGES_KEY = "translation_languages"
DEFAULT_LANGUAGES = {
    "en": "Английский", "es": "Испанский", "pt": "Португальский",
    "ar": "Арабский", "ru": "Русский", "fr": "Французский",
    "de": "Немецкий", "it": "Итальянский", "tr": "Турецкий",
    "hi": "Хинди", "uz": "Узбекский",
}


class TranslationLanguage(BaseModel):
    value: str = Field(min_length=2, max_length=10, pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
    label: str = Field(min_length=1, max_length=80)

    @field_validator("value", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().lower().replace("_", "-") if isinstance(value, str) else value

    @field_validator("label", mode="before")
    @classmethod
    def trim_label(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


async def get_languages(service: SystemSettingService) -> list[TranslationLanguage]:
    custom = json.loads(await service.get_value(LANGUAGES_KEY) or "{}")
    return [TranslationLanguage(value=code, label=label)
            for code, label in (DEFAULT_LANGUAGES | custom).items()]
