import ast
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.traffic_expression import METRICS, parse_expression


class QualityRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    destination: Literal["all", "bot", "channel"] = "all"
    bot_ids: list[UUID] = Field(default_factory=list, max_length=100)
    ad_types: list[str] = Field(default_factory=list, max_length=30)
    expression: str = "percent(tagged_leads, assessed_leads)"
    operator: Literal["lt", "gt"] = "gt"
    threshold: float = Field(default=25, ge=0, le=1e9, allow_inf_nan=False)
    recovery_threshold: float = Field(default=20, ge=0, le=1e9, allow_inf_nan=False)
    window_hours: int = Field(default=168, ge=1, le=2160)
    maturation_hours: int = Field(default=24, ge=0, le=720)
    sample_metric: str = "assessed_leads"
    min_sample: int = Field(default=40, ge=1, le=1000000)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=100)
    tag_match: Literal["any", "all"] = "any"
    assessed_tag_ids: list[UUID] = Field(default_factory=list, max_length=100)
    assessed_status_codes: list[str] = Field(default_factory=list, max_length=100)
    min_coverage: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    confirmations: int = Field(default=2, ge=1, le=12)
    repeat_hours: int = Field(default=24, ge=1, le=720)
    severity: Literal["warning", "critical"] = "warning"
    notify_buyer: bool = True
    notify_admin: bool = True
    notify_recovery: bool = True

    @field_validator("expression")
    @classmethod
    def expression_valid(cls, value):
        parse_expression(value)
        return value

    @field_validator("sample_metric")
    @classmethod
    def metric_valid(cls, value):
        if value not in METRICS - {"spend", "coverage"}:
            raise ValueError("Неизвестный показатель выборки")
        return value

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.operator == "gt" and self.recovery_threshold > self.threshold:
            raise ValueError("Порог восстановления должен быть не выше порога тревоги")
        if self.operator == "lt" and self.recovery_threshold < self.threshold:
            raise ValueError("Порог восстановления должен быть не ниже порога тревоги")
        names = {node.id for node in ast.walk(parse_expression(self.expression)) if isinstance(node, ast.Name)} | {self.sample_metric}
        if "tagged_leads" in names and not self.tag_ids:
            raise ValueError("Выберите теги для показателя tagged_leads")
        if ("assessed_leads" in names or self.min_coverage > 0) and not (self.assessed_tag_ids or self.assessed_status_codes):
            raise ValueError("Укажите теги или статусы завершённой оценки")
        if self.destination == "bot" and any(name.startswith("channel_") for name in names):
            raise ValueError("Канальные показатели недоступны для ссылок на бота")
        if "spend" in names and (self.window_hours % 24 or self.maturation_hours % 24):
            raise ValueError("Для расходов период и время ожидания задаются кратно 24 часам")
        return self


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    timezone: str = "Europe/Moscow"
    rules: list[QualityRule] = Field(default_factory=list, max_length=30)
    revision: int = Field(default=0, ge=0)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Неизвестный часовой пояс") from exc
        return value

    @model_validator(mode="after")
    def unique_rules(self):
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("Повторяющиеся ID правил")
        return self


class QualityOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Only changed fields are stored, so other project settings keep inheriting.
    patches: dict[UUID, dict] = Field(default_factory=dict, max_length=30)
    rules: list[QualityRule] = Field(default_factory=list, max_length=10)
    revision: int = Field(default=0, ge=0)


def effective_rules(config: QualityConfig, overrides: QualityOverrides) -> list[QualityRule]:
    rules = []
    known = {rule.id for rule in config.rules}
    for rule in config.rules:
        patch = overrides.patches.get(rule.id, {})
        if "id" in patch:
            raise ValueError("Нельзя изменить ID правила")
        rules.append(QualityRule.model_validate({**rule.model_dump(), **patch}))
    for rule in overrides.rules:
        if rule.id in known or any(item.id == rule.id for item in rules):
            raise ValueError("Повторяющиеся ID правил")
        rules.append(rule)
    return rules
