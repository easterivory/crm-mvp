from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_file_logging() -> None:
    """Add one bounded per-service log file while preserving console logs."""
    root = logging.getLogger()
    if any(getattr(handler, "_crm_file_handler", False) for handler in root.handlers):
        return

    log_dir = Path(settings.LOG_STORAGE_PATH)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        service_name = _safe_service_name(settings.APP_SERVICE_NAME)
        handler = RotatingFileHandler(
            log_dir / f"{service_name}.log",
            maxBytes=max(settings.LOG_FILE_MAX_MB, 1) * 1024 * 1024,
            backupCount=max(settings.LOG_FILE_BACKUP_COUNT, 1),
            encoding="utf-8",
        )
    except OSError:
        logging.getLogger(__name__).warning(
            "Could not initialize file logging path=%s",
            log_dir,
            exc_info=True,
        )
        return
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        UTCFormatter(
            "%(asctime)sZ %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler._crm_file_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)


def _safe_service_name(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in "-_" else "-" for char in value)
    return normalized.strip("-") or "app"
