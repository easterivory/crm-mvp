from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID


TELEGRAM_COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
CUSTOM_COMMAND_TRIGGER_TYPE = "custom_command"
MAX_TELEGRAM_COMMANDS = 100


@dataclass(frozen=True)
class FunnelTelegramCommand:
    command: str
    description: str
    step_id: UUID


def normalize_telegram_command(value: object) -> str:
    command = str(value or "").strip().lower()
    if command.startswith("/"):
        command = command[1:]
    command = command.split("@", 1)[0]
    return command


def extract_telegram_command(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not value.startswith("/"):
        return None
    command = normalize_telegram_command(value.split(maxsplit=1)[0])
    return command if TELEGRAM_COMMAND_RE.fullmatch(command) else None


def is_custom_command_trigger(step: Any) -> bool:
    if getattr(step, "step_type", None) != "trigger":
        return False
    if getattr(step, "block_type", None) != "generic_trigger":
        return False
    config = getattr(step, "config_json", None)
    return (
        isinstance(config, dict)
        and str(config.get("trigger_type") or "").strip() == CUSTOM_COMMAND_TRIGGER_TYPE
    )


def command_from_trigger_step(step: Any) -> FunnelTelegramCommand | None:
    if not is_custom_command_trigger(step):
        return None
    config = step.config_json
    command = normalize_telegram_command(config.get("command"))
    step_id = getattr(step, "id", None)
    if not TELEGRAM_COMMAND_RE.fullmatch(command) or not isinstance(step_id, UUID):
        return None
    description = str(
        config.get("command_description") or getattr(step, "title", "") or ""
    ).strip()
    if not description:
        description = f"Команда /{command}"
    return FunnelTelegramCommand(
        command=command,
        description=description[:256],
        step_id=step_id,
    )


def collect_funnel_telegram_commands(
    steps: Iterable[Any],
) -> list[FunnelTelegramCommand]:
    commands: list[FunnelTelegramCommand] = []
    seen: set[str] = set()
    for step in steps:
        definition = command_from_trigger_step(step)
        if definition is None or definition.command in seen:
            continue
        seen.add(definition.command)
        commands.append(definition)
    return commands
