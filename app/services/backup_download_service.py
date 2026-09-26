"""Temporary database archives for authenticated root downloads."""
from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID

from app.core.config import Settings, settings
from app.services.backup_service import BackupResult, create_database_backup

DOWNLOAD_TTL_SECONDS = 24 * 60 * 60


def download_directory(config: Settings = settings) -> Path:
    return Path(config.BACKUP_STORAGE_PATH) / "downloads"


def cleanup_downloads(config: Settings = settings) -> None:
    directory = download_directory(config)
    if not directory.exists():
        return
    cutoff = time.time() - DOWNLOAD_TTL_SECONDS
    for path in directory.iterdir():
        if (path.name.startswith(("download_", ".download_"))
                and path.is_file() and path.stat().st_mtime < cutoff):
            path.unlink(missing_ok=True)


def create_download(job_id: str, config: Settings = settings) -> BackupResult:
    identifier = UUID(job_id)
    cleanup_downloads(config)
    # Downloads have their own expiry, independent of scheduled backup retention.
    config = config.model_copy(update={"BACKUP_RETENTION_COUNT": -1, "BACKUP_RETENTION_DAYS": 0})
    return create_database_backup(
        config=config, output_dir=download_directory(config),
        backup_name=f"download_{identifier}", send_to_telegram=False,
    )


def resolve_download(job_id: UUID, filename: str, config: Settings = settings) -> Path:
    if filename not in {f"download_{job_id}.sql.gz", f"download_{job_id}.sql.gz.enc"}:
        raise ValueError("Invalid backup filename")
    directory = download_directory(config).resolve()
    path = directory / filename
    if path.is_symlink() or path.resolve().parent != directory:
        raise ValueError("Invalid backup path")
    if not path.is_file() or path.stat().st_mtime < time.time() - DOWNLOAD_TTL_SECONDS:
        raise FileNotFoundError("Backup expired")
    return path
