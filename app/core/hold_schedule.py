"""Project calendar for opt-in funnel HOLD routing (no periodic worker)."""
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HoldSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    timezone: str = Field(default="Europe/Moscow", max_length=100)
    cutoff_time: str = Field(default="18:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    working_days: list[int] = Field(default_factory=lambda: list(range(6)), min_length=1, max_length=7)
    before_cutoff: Literal["today", "next_working_day"] = "today"
    closed_dates: list[date] = Field(default_factory=list, max_length=366)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @field_validator("working_days", mode="before")
    @classmethod
    def validate_days(cls, value):
        if not isinstance(value, list) or any(type(day) is not int or not 0 <= day <= 6 for day in value):
            raise ValueError("Working days must be integers from 0 (Monday) to 6 (Sunday)")
        return sorted(set(value))

    @field_validator("closed_dates")
    @classmethod
    def unique_dates(cls, value):
        return sorted(set(value))


def scheduled_hold_plan(schedule: HoldSchedule, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("HOLD clock must be timezone-aware")
    local = now.astimezone(ZoneInfo(schedule.timezone))
    today = local.date()
    hour, minute = map(int, schedule.cutoff_time.split(":"))
    allow_today = schedule.before_cutoff == "today" and (local.hour, local.minute) < (hour, minute)
    target = today if allow_today else today + timedelta(days=1)
    closed = set(schedule.closed_dates)
    # The settings permit at most 366 closed dates; this bound covers weekly gaps too.
    for _ in range(2600):
        if target.weekday() in schedule.working_days and target not in closed:
            break
        target += timedelta(days=1)
    else:
        raise ValueError("No working date available")
    return {
        "date": target.isoformat(),
        "date_label": target.strftime("%d.%m.%Y"),
        "is_hold": target != today,
        "timezone": schedule.timezone,
        "calculated_at": now.isoformat(),
    }
