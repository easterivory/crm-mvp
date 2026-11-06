from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.postback import PostbackParameterMapping


class PayoutTier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: int = Field(ge=1, le=10000000)
    rate: Decimal | None = Field(default=None, ge=0, le=1000000000)
    bonus: Decimal | None = Field(default=None, ge=0, le=1000000000)

    @field_validator("rate", "bonus")
    @classmethod
    def money(cls, value):
        if value is not None and (not value.is_finite() or value != value.quantize(Decimal("0.01"))):
            raise ValueError("Сумма должна содержать не более двух знаков после запятой")
        return value

    @model_validator(mode="after")
    def one_reward(self):
        if (self.rate is None) == (self.bonus is None):
            raise ValueError("Выберите ставку или бонус для каждого порога")
        return self


class PayoutTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate: Decimal = Field(default=Decimal("0"), ge=0, le=1000000000, decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3,10}$")
    min_deposit: Decimal = Field(default=Decimal("0"), ge=0, le=1000000000, decimal_places=2)
    deposit_currency: str = Field(default="USD", pattern=r"^[A-Z]{3,10}$")
    qualification_param: str | None = Field(default=None, min_length=1, max_length=255)
    qualification_values: list[str] = Field(default_factory=lambda: ["1", "true", "approved"], max_length=50)
    qualification_rejected_values: list[str] = Field(default_factory=lambda: ["0", "false", "rejected", "declined"], max_length=50)
    period: Literal["day", "week", "month", "custom"] = "month"
    timezone: str = "Europe/Moscow"
    period_from: date | None = None
    period_to: date | None = None
    tier_mode: Literal["excess", "retroactive"] = "excess"
    tiers: list[PayoutTier] = Field(default_factory=list, max_length=50)
    conditions_note: str = Field(default="", max_length=2000)

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError("Неизвестный часовой пояс") from None
        return value

    @model_validator(mode="after")
    def valid_period_and_tiers(self):
        if self.period == "custom" and (not self.period_from or not self.period_to or self.period_to < self.period_from
                                       or (self.period_to - self.period_from).days > 365):
            raise ValueError("Задайте период до 366 дней включительно")
        values = [tier.threshold for tier in self.tiers]
        if values != sorted(set(values)):
            raise ValueError("Пороги должны быть уникальны и идти по возрастанию")
        if self.qualification_param and not self.qualification_values:
            raise ValueError("Укажите значения подтверждённой квалификации")
        if any(not value.strip() for value in self.qualification_values + self.qualification_rejected_values):
            raise ValueError("Значения квалификации не могут быть пустыми")
        if {v.strip().casefold() for v in self.qualification_values}.intersection(v.strip().casefold() for v in self.qualification_rejected_values):
            raise ValueError("Значения подтверждения и отказа не должны совпадать")
        return self


class PayoutPolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    partner_name: str = Field(min_length=1, max_length=255)
    count_scope: Literal["offer", "partner_group"] = "offer"
    terms: PayoutTerms

    @field_validator("name", "partner_name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError("Поле не может быть пустым")
        return value.strip()


class OfferWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    partner_name: str = Field(min_length=1, max_length=255)
    source_url: str = Field(min_length=1, max_length=8192)
    postbacks_enabled: bool = False
    identifier_parameter: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")
    postback_mapping: PostbackParameterMapping | None = None
    payout_policy_id: UUID | None = None
    is_active: bool = True

    @field_validator("name", "partner_name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError("Поле не может быть пустым")
        return value.strip()

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        # Never fetch this URL. Reject obvious unsafe URLs and template nesting.
        try:
            p = urlsplit(value)
            port = p.port
        except ValueError: raise ValueError("Некорректная ссылка") from None
        if (p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password
                or "{{" in value or "}}" in value or any(ord(c) < 33 for c in value)
                or p.hostname.lower() in {"localhost", "localhost.localdomain"}):
            raise ValueError("Нужна полная публичная HTTP(S)-ссылка без переменных")
        try: address = ipaddress.ip_address(p.hostname)
        except ValueError: address = None
        if address is not None and not address.is_global: raise ValueError("Непубличный IP")
        return value

    @model_validator(mode="after")
    def postback_contract(self):
        if self.postbacks_enabled and (not self.identifier_parameter or not self.postback_mapping):
            raise ValueError("Для постбэков укажите параметр ссылки и правила входящего запроса")
        if self.postbacks_enabled and not self.postback_mapping.event_type_param:
            raise ValueError("Укажите поле типа события REG / FD / RD")
        if self.postbacks_enabled and self.postback_mapping.bind_external_id_param and self.postback_mapping.bind_external_type != "player_id":
            raise ValueError("В оффере внешняя привязка предназначена для Player ID")
        return self


class FunnelOfferWrite(BaseModel):
    offer_id: UUID | None = None


class QualificationWrite(BaseModel):
    qualified: bool
    reason: str = Field(min_length=1, max_length=255)
    occurred_at: datetime | None = None

    @field_validator("occurred_at")
    @classmethod
    def actual_time(cls, value):
        if value and (value.tzinfo is None or value.year < 2000 or value > datetime.now(timezone.utc) + timedelta(minutes=5)):
            raise ValueError("Нужно фактическое время FD с часовым поясом")
        return value
