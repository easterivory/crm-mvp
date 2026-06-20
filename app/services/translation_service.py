from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_setting_service import SystemSettingService

logger = logging.getLogger(__name__)

TRANSLATION_PROVIDER_KEY = "translation_provider"
TRANSLATION_API_KEY = "translation_api_key"
TRANSLATION_BASE_URL_KEY = "translation_base_url"

TranslationProvider = Literal["deepl", "google", "libretranslate"]


class TranslationUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    provider: TranslationProvider | None
    api_key: str | None
    base_url: str | None


class TranslationService:
    def __init__(self, db: AsyncSession, *, timeout: float = 15.0) -> None:
        self.settings = SystemSettingService(db)
        self.timeout = timeout

    async def translate_text(
        self,
        text: str,
        source_lang: Optional[str],
        target_lang: str,
        *,
        raise_on_failure: bool = False,
    ) -> str:
        if not text.strip():
            return text

        source = self._normalize_lang(source_lang)
        target = self._normalize_lang(target_lang)
        if target is None:
            logger.warning("Translation target language is empty; returning original text")
            return text
        if source is not None and source == target:
            return text

        config = await self._get_settings()
        if config.provider is None:
            logger.warning("Translation provider is not configured")
            if raise_on_failure:
                raise TranslationUnavailableError("Translation provider is not configured")
            return text

        try:
            if config.provider == "deepl":
                return await self._translate_deepl(text, source, target, config)
            if config.provider == "google":
                return await self._translate_google(text, source, target, config)
            return await self._translate_libretranslate(text, source, target, config)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Translation provider returned HTTP error provider=%s status_code=%s response=%s",
                config.provider,
                exc.response.status_code,
                exc.response.text[:500],
            )
            if raise_on_failure:
                raise TranslationUnavailableError(
                    f"Translation provider returned HTTP {exc.response.status_code}"
                ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "Translation provider is unavailable provider=%s error_type=%s",
                config.provider,
                exc.__class__.__name__,
            )
            if raise_on_failure:
                raise TranslationUnavailableError("Translation provider is unavailable") from exc
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Translation provider returned unexpected payload provider=%s error=%s",
                config.provider,
                exc,
            )
            if raise_on_failure:
                raise TranslationUnavailableError("Translation provider returned unexpected payload") from exc
        except Exception as exc:
            logger.warning(
                "Unexpected translation failure provider=%s error=%s",
                config.provider,
                exc,
                exc_info=True,
            )
            if raise_on_failure:
                raise TranslationUnavailableError("Unexpected translation failure") from exc
        return text

    async def _get_settings(self) -> TranslationSettings:
        provider_raw = await self.settings.get_value(TRANSLATION_PROVIDER_KEY)
        api_key = self._normalize_optional(await self.settings.get_value(TRANSLATION_API_KEY))
        base_url = self._normalize_base_url(await self.settings.get_value(TRANSLATION_BASE_URL_KEY))
        return TranslationSettings(
            provider=self._normalize_provider(provider_raw),
            api_key=api_key,
            base_url=base_url,
        )

    async def _translate_deepl(
        self,
        text: str,
        source_lang: str | None,
        target_lang: str,
        config: TranslationSettings,
    ) -> str:
        if not config.api_key:
            logger.warning("DeepL translation API key is not configured; returning original text")
            return text

        payload = {
            "auth_key": config.api_key,
            "text": text,
            "target_lang": self._deepl_target_lang(target_lang),
        }
        if source_lang is not None:
            payload["source_lang"] = source_lang.upper()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._endpoint_url(
                    config.base_url,
                    self._deepl_default_base_url(config.api_key),
                    "/v2/translate",
                ),
                data=payload,
            )
            response.raise_for_status()
            data = response.json()

        translations = data["translations"]
        if not isinstance(translations, list) or not translations:
            raise ValueError("DeepL response has no translations")
        translated = translations[0]["text"]
        if not isinstance(translated, str):
            raise TypeError("DeepL translated text is not a string")
        return translated

    async def _translate_google(
        self,
        text: str,
        source_lang: str | None,
        target_lang: str,
        config: TranslationSettings,
    ) -> str:
        if not config.api_key:
            logger.warning("Google Translate API key is not configured; returning original text")
            return text

        payload = {
            "q": text,
            "target": target_lang,
            "format": "text",
        }
        if source_lang is not None:
            payload["source"] = source_lang

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._endpoint_url(
                    config.base_url,
                    "https://translation.googleapis.com",
                    "/language/translate/v2",
                ),
                params={"key": config.api_key},
                data=payload,
            )
            response.raise_for_status()
            data = response.json()

        translations = data["data"]["translations"]
        if not isinstance(translations, list) or not translations:
            raise ValueError("Google Translate response has no translations")
        translated = translations[0]["translatedText"]
        if not isinstance(translated, str):
            raise TypeError("Google translated text is not a string")
        return html.unescape(translated)

    async def _translate_libretranslate(
        self,
        text: str,
        source_lang: str | None,
        target_lang: str,
        config: TranslationSettings,
    ) -> str:
        payload: dict[str, Any] = {
            "q": text,
            "source": source_lang or "auto",
            "target": target_lang,
            "format": "text",
        }
        if config.api_key:
            payload["api_key"] = config.api_key

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._endpoint_url(config.base_url, "http://localhost:5000", "/translate"),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        translated = data["translatedText"]
        if not isinstance(translated, str):
            raise TypeError("LibreTranslate translated text is not a string")
        return translated

    @staticmethod
    def _endpoint_url(base_url: str | None, default_base_url: str, path: str) -> str:
        base = (base_url or default_base_url).rstrip("/")
        return base if base.endswith(path) else f"{base}{path}"

    @staticmethod
    def _normalize_provider(provider: str | None) -> TranslationProvider | None:
        normalized = TranslationService._normalize_optional(provider)
        if normalized is None:
            return None

        value = normalized.lower().replace("_", "-")
        aliases: dict[str, TranslationProvider] = {
            "deepl": "deepl",
            "deep-l": "deepl",
            "google": "google",
            "google-translate": "google",
            "libre": "libretranslate",
            "libre-translate": "libretranslate",
            "libretranslate": "libretranslate",
        }
        provider_value = aliases.get(value)
        if provider_value is None:
            logger.warning("Unsupported translation provider=%s; returning original text", provider)
        return provider_value

    @staticmethod
    def _normalize_lang(value: str | None) -> str | None:
        normalized = TranslationService._normalize_optional(value)
        if normalized is None:
            return None
        return normalized.replace("_", "-").lower()

    @staticmethod
    def _deepl_target_lang(value: str) -> str:
        if value == "en":
            return "EN-US"
        return value.upper()

    @staticmethod
    def _deepl_default_base_url(api_key: str | None) -> str:
        if api_key and api_key.strip().endswith(":fx"):
            return "https://api-free.deepl.com"
        return "https://api.deepl.com"

    @staticmethod
    def _normalize_optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_base_url(value: str | None) -> str | None:
        normalized = TranslationService._normalize_optional(value)
        return normalized.rstrip("/") if normalized is not None else None
