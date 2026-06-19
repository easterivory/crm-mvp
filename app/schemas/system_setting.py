from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class BuyerBotConfigOut(BaseModel):
    token: Optional[str] = None
    username: Optional[str] = None


class BuyerBotConfigUpdate(BaseModel):
    token: Optional[str] = Field(default=None, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)

    @field_validator("token", "username", mode="before")
    @classmethod
    def trim_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: Optional[str]) -> Optional[str]:
        return value.removeprefix("@") if value else value


TranslationProvider = Literal["deepl", "google", "libretranslate"]


class TranslationProviderConfigOut(BaseModel):
    provider: Optional[TranslationProvider] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class TranslationProviderConfigUpdate(BaseModel):
    provider: Optional[TranslationProvider] = None
    api_key: Optional[str] = Field(default=None, max_length=500)
    base_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("api_key", "base_url", mode="before")
    @classmethod
    def trim_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value
