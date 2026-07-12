from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)


class FacebookCAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class FacebookCAPIService:
    EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    PIXEL_ID_RE = re.compile(r"^\d{5,50}$")

    @staticmethod
    def hash_data(value: str) -> str:
        normalized = re.sub(r"\s+", "", value.strip().lower()).replace("+", "")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    async def send_event(
        cls,
        *,
        pixel_id: str,
        token: str,
        event_name: str,
        lead: Lead,
        event_time: int | None = None,
        custom_data: dict[str, Any] | None = None,
        event_id: str | None = None,
        event_source_url: str | None = None,
        proxy_url: str | None = None,
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        normalized_pixel_id = cls.validate_pixel_id(pixel_id)
        normalized_token = cls.validate_token(token)
        normalized_event_name = cls.validate_event_name(event_name)
        event_time = cls.validate_event_time(event_time)
        payload = cls.build_payload(
            event_name=normalized_event_name,
            lead=lead,
            event_time=event_time,
            custom_data=custom_data,
            event_id=event_id,
            event_source_url=event_source_url,
            test_event_code=test_event_code,
        )
        graph_version = cls.validate_graph_api_version(settings.FACEBOOK_GRAPH_API_VERSION)
        url = f"https://graph.facebook.com/{graph_version}/{normalized_pixel_id}/events"

        client_kwargs: dict[str, Any] = {
            "timeout": settings.FACEBOOK_CAPI_TIMEOUT_SECONDS,
        }
        normalized_proxy = cls.validate_proxy_url(proxy_url)
        if normalized_proxy:
            client_kwargs["proxy"] = normalized_proxy
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    url,
                    params={"access_token": normalized_token},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise FacebookCAPIError(
                f"Facebook CAPI network error: {exc}",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "Facebook CAPI request failed pixel_id=%s event_name=%s status=%s body=%s",
                normalized_pixel_id,
                normalized_event_name,
                response.status_code,
                response.text[:1000],
            )
            raise FacebookCAPIError(
                f"Facebook CAPI HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise FacebookCAPIError("Facebook CAPI returned non-JSON response") from exc

        logger.info(
            "Facebook CAPI event sent pixel_id=%s event_name=%s lead_id=%s response=%s",
            normalized_pixel_id,
            normalized_event_name,
            lead.id,
            data,
        )
        return data

    @classmethod
    def build_payload(
        cls,
        *,
        event_name: str,
        lead: Lead,
        event_time: int,
        custom_data: dict[str, Any] | None,
        event_id: str | None = None,
        event_source_url: str | None = None,
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        user_data = cls.build_user_data(lead)
        event: dict[str, Any] = {
            "event_name": event_name,
            "event_time": event_time,
            "event_id": cls.validate_event_id(
                event_id or f"lead:{lead.id}:{event_name}:{event_time}"
            ),
            "action_source": "website",
            "user_data": user_data,
        }
        normalized_source_url = cls.validate_event_source_url(event_source_url)
        if normalized_source_url:
            event["event_source_url"] = normalized_source_url
        cleaned_custom_data = cls.clean_custom_data(custom_data)
        if cleaned_custom_data:
            event["custom_data"] = cleaned_custom_data
        payload: dict[str, Any] = {"data": [event]}
        normalized_test_code = cls._clean_string(test_event_code)
        if normalized_test_code:
            payload["test_event_code"] = normalized_test_code
        return payload

    @classmethod
    def build_user_data(cls, lead: Lead) -> dict[str, Any]:
        custom_fields = lead.custom_fields if isinstance(lead.custom_fields, dict) else {}
        fb_data = custom_fields.get("fb_data")
        if not isinstance(fb_data, dict):
            fb_data = {}

        user_data: dict[str, Any] = {}
        for source_key, target_key in (
            ("client_ip_address", "client_ip_address"),
            ("client_user_agent", "client_user_agent"),
            ("fbp", "fbp"),
            ("fbc", "fbc"),
        ):
            value = cls._clean_string(fb_data.get(source_key))
            if value:
                user_data[target_key] = value

        external_user_id = cls._clean_string(getattr(getattr(lead, "chat", None), "external_user_id", None))
        if external_user_id:
            user_data["external_id"] = [cls.hash_data(external_user_id)]

        phone_hash = cls._hash_phone(lead.phone)
        if phone_hash:
            user_data["ph"] = [phone_hash]

        email = cls._clean_string(custom_fields.get("email") or custom_fields.get("em"))
        if email:
            user_data["em"] = [cls.hash_data(email)]

        first_name = cls._clean_string(custom_fields.get("first_name")) or cls._first_name(lead.name)
        if first_name:
            user_data["fn"] = [cls.hash_data(first_name)]

        last_name = cls._clean_string(custom_fields.get("last_name"))
        if last_name:
            user_data["ln"] = [cls.hash_data(last_name)]

        country = cls._clean_string(lead.country)
        if country:
            user_data["country"] = [cls.hash_data(country)]

        if not user_data:
            raise FacebookCAPIError("No user_data available for Facebook CAPI event")
        return user_data

    @classmethod
    def validate_event_name(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not cls.EVENT_NAME_RE.fullmatch(normalized):
            raise FacebookCAPIError(
                "Facebook event_name must use Latin letters, numbers, or underscores "
                "and be 1-40 characters long"
            )
        return normalized

    @classmethod
    def validate_pixel_id(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not cls.PIXEL_ID_RE.fullmatch(normalized):
            raise FacebookCAPIError("fb_pixel_id must contain 5-50 digits")
        return normalized

    @staticmethod
    def validate_token(value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise FacebookCAPIError("fb_capi_token is required")
        return normalized

    @staticmethod
    def validate_graph_api_version(value: str) -> str:
        normalized = (value or "").strip().lower()
        if not re.fullmatch(r"v\d{1,2}\.\d", normalized):
            raise FacebookCAPIError("Invalid FACEBOOK_GRAPH_API_VERSION")
        return normalized

    @staticmethod
    def validate_event_id(value: str) -> str:
        normalized = (value or "").strip()
        if not normalized or len(normalized) > 100:
            raise FacebookCAPIError("Facebook event_id must be 1-100 characters long")
        if any(character in normalized for character in ("\r", "\n", "\t")):
            raise FacebookCAPIError("Facebook event_id contains unsupported whitespace")
        return normalized

    @staticmethod
    def validate_event_source_url(value: str | None) -> str | None:
        normalized = (value or "").strip()
        if not normalized:
            return None
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        return normalized[:2048]

    @staticmethod
    def validate_proxy_url(value: str | None) -> str | None:
        normalized = (value or "").strip()
        if not normalized:
            return None
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise FacebookCAPIError("Facebook proxy URL must use http or https")
        return normalized

    @staticmethod
    def validate_event_time(value: int | None) -> int:
        if value is None:
            return int(time.time())
        if value <= 0:
            raise FacebookCAPIError("event_time must be a positive unix timestamp")
        now = int(time.time())
        if value > now + 300:
            raise FacebookCAPIError("event_time must not be in the future")
        if value < now - 7 * 24 * 60 * 60:
            raise FacebookCAPIError("event_time is older than seven days")
        return value

    @staticmethod
    def clean_custom_data(custom_data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(custom_data, dict):
            return {}
        cleaned = {
            str(key): value
            for key, value in custom_data.items()
            if isinstance(key, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,49}", key)
            and value is not None
        }
        if "currency" in cleaned:
            currency = str(cleaned["currency"]).strip().upper()
            if re.fullmatch(r"[A-Z]{3}", currency):
                cleaned["currency"] = currency
            else:
                cleaned.pop("currency", None)
        return cleaned

    @staticmethod
    def _hash_phone(value: str | None) -> str | None:
        digits = re.sub(r"\D+", "", value or "")
        if not digits:
            return None
        return FacebookCAPIService.hash_data(digits)

    @staticmethod
    def _clean_string(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _first_name(value: str | None) -> str | None:
        cleaned = FacebookCAPIService._clean_string(value)
        if not cleaned:
            return None
        return cleaned.split(maxsplit=1)[0]
