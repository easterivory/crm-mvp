from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.core.config import settings


LOG_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z\s")
BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
BEARER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+")
SECRET_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|bot[_-]?token|password|secret)\b\s*[:=]\s*)"
    r"([^\s,;]+)"
)


class ServerLogExportError(RuntimeError):
    pass


def collect_recent_server_logs(*, minutes: int = 30) -> bytes:
    cutoff = datetime.now(UTC) - timedelta(minutes=max(minutes, 1))
    log_dir = Path(settings.LOG_STORAGE_PATH)
    sections: list[str] = []
    remaining_bytes = max(settings.LOG_EXPORT_MAX_MB, 1) * 1024 * 1024

    candidates = (
        sorted(
            (path for path in log_dir.glob("*.log*") if path.is_file()),
            key=lambda path: path.name,
        )
        if log_dir.exists()
        else []
    )

    for path in candidates:
        if remaining_bytes <= 0:
            break
        try:
            section = _recent_records_from_file(path, cutoff, max_bytes=remaining_bytes)
        except OSError:
            continue
        if not section:
            continue
        rendered = f"\n===== {path.name} =====\n{section}"
        encoded = rendered.encode("utf-8", errors="replace")
        if len(encoded) > remaining_bytes:
            encoded = encoded[-remaining_bytes:]
            rendered = encoded.decode("utf-8", errors="replace")
        sections.append(rendered)
        remaining_bytes -= len(rendered.encode("utf-8"))

    header = (
        f"CRM server logs\n"
        f"generated_at_utc={datetime.now(UTC).isoformat()}\n"
        f"period_minutes={minutes}\n"
        f"files={len(sections)}\n"
    )
    body = "".join(sections) or "\nNo application log records were found for this period.\n"
    return (header + body).encode("utf-8", errors="replace")


async def send_server_logs_to_telegram(
    content: bytes,
    *,
    bot_token: str,
    chat_id: str,
    minutes: int = 30,
) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_UTC")
    filename = f"crm_server_logs_{timestamp}.txt"
    url = f"{settings.BACKUP_TELEGRAM_API_BASE_URL.rstrip('/')}/bot{bot_token}/sendDocument"
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            data={
                "chat_id": chat_id,
                "caption": f"CRM server logs for the last {minutes} minutes",
            },
            files={"document": (filename, content, "text/plain")},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ServerLogExportError("Telegram returned a non-JSON response") from exc
    if response.status_code >= 400 or payload.get("ok") is not True:
        description = payload.get("description") or response.text[:500]
        raise ServerLogExportError(
            f"Telegram log upload failed: HTTP {response.status_code}: {description}"
        )
    return filename


def _recent_records_from_file(path: Path, cutoff: datetime, *, max_bytes: int) -> str:
    read_limit = min(max(max_bytes * 2, 256 * 1024), 8 * 1024 * 1024)
    with path.open("rb") as file:
        size = path.stat().st_size
        if size > read_limit:
            file.seek(size - read_limit)
            file.readline()
        raw = file.read(read_limit).decode("utf-8", errors="replace")

    selected: list[str] = []
    include_record = False
    for line in raw.splitlines():
        match = LOG_TIMESTAMP_RE.match(line)
        if match:
            occurred_at = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            include_record = occurred_at >= cutoff
        if include_record:
            selected.append(_redact(line))
    return "\n".join(selected)


def _redact(value: str) -> str:
    redacted = BOT_TOKEN_RE.sub("[REDACTED_BOT_TOKEN]", value)
    redacted = BEARER_RE.sub(r"\1[REDACTED]", redacted)
    return SECRET_RE.sub(r"\1[REDACTED]", redacted)
