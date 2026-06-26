from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)


class FacebookCAPIError(RuntimeError):
    pass


class FacebookCAPIService:
    GRAPH_API_VERSION = "v19.0"
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
        )
        url = f"https://graph.facebook.com/{cls.GRAPH_API_VERSION}/{normalized_pixel_id}/events"

        async with httpx.AsyncClient(timeout=settings.FACEBOOK_CAPI_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                params={"access_token": normalized_token},
                json=payload,
            )

        if response.status_code >= 400:
            logger.warning(
                "Facebook CAPI request failed pixel_id=%s event_name=%s status=%s body=%s",
                normalized_pixel_id,
                normalized_event_name,
                response.status_code,
                response.text[:1000],
            )
            raise FacebookCAPIError(
                f"Facebook CAPI HTTP {response.status_code}: {response.text[:500]}"
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
    ) -> dict[str, Any]:
        user_data = cls.build_user_data(lead)
        event: dict[str, Any] = {
            "event_name": event_name,
            "event_time": event_time,
            "event_id": f"lead:{lead.id}:{event_name}:{event_time}",
            "action_source": "website",
            "user_data": user_data,
        }
        cleaned_custom_data = cls.clean_custom_data(custom_data)
        if cleaned_custom_data:
            event["custom_data"] = cleaned_custom_data
        return {"data": [event]}

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

        first_name = cls._first_name(lead.name)
        if first_name:
            user_data["fn"] = [cls.hash_data(first_name)]

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
    def validate_event_time(value: int | None) -> int:
        if value is None:
            return int(time.time())
        if value <= 0:
            raise FacebookCAPIError("event_time must be a positive unix timestamp")
        return value

    @staticmethod
    def clean_custom_data(custom_data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(custom_data, dict):
            return {}
        return {
            str(key): value
            for key, value in custom_data.items()
            if isinstance(key, str) and value is not None
        }

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
