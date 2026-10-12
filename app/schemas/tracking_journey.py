from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class JourneyStepReference(BaseModel):
    funnel_id: UUID
    key: str = Field(min_length=1, max_length=255)


class JourneyStage(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=80)
    source: Literal["start", "entered", "answered", "tag"]
    step_keys: list[str] = Field(default_factory=list, max_length=50)
    step_refs: list[JourneyStepReference] = Field(default_factory=list, max_length=50)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)
    role: Literal["regular", "offer", "outcome"] = "regular"

    @model_validator(mode="after")
    def valid_source(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Название этапа не может быть пустым")
        if self.source in {"entered", "answered"} and not (self.step_keys or self.step_refs):
            raise ValueError("Выберите шаги этапа")
        if self.source == "tag" and not self.tag_ids:
            raise ValueError("Выберите теги этапа")
        if (self.source != "tag" and self.tag_ids) or (self.source not in {"entered", "answered"} and (self.step_keys or self.step_refs)):
            raise ValueError("Источник этапа не соответствует выбранным условиям")
        if self.role == "outcome" and self.source != "tag":
            raise ValueError("Итоговый этап должен определяться тегом")
        return self


class JourneyConfig(BaseModel):
    stages: list[JourneyStage] = Field(min_length=1, max_length=400)
    mode: Literal["stages", "steps"] = "stages"
    idle_hours: int = Field(default=24, ge=1, le=8760)
    scope: Literal["bot", "funnel"] = "bot"

    @model_validator(mode="after")
    def valid_stages(self):
        if self.mode == "stages" and not 2 <= len(self.stages) <= 20:
            raise ValueError("Настройте от 2 до 20 этапов")
        if len({stage.id for stage in self.stages}) != len(self.stages):
            raise ValueError("Идентификаторы этапов должны быть уникальными")
        if self.stages[0].source != "start" or any(s.source == "start" for s in self.stages[1:]):
            raise ValueError("Первый этап — старт, он может быть только один")
        if self.stages[0].role != "regular":
            raise ValueError("Старт не может быть этапом предложения или итоговым этапом")
        if self.mode == "steps":
            if any(s.role != "regular" or s.source != "entered" for s in self.stages[1:]):
                raise ValueError("Обзор шагов содержит только входы на шаги")
            return self
        if self.stages[-1].role != "outcome" or sum(s.role == "outcome" for s in self.stages) != 1:
            raise ValueError("Последний этап — единственный итоговый этап по тегу")
        if sum(s.role == "offer" for s in self.stages) > 1:
            raise ValueError("Этап ознакомления с предложением может быть только один")
        return self
