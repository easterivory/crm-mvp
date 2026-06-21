from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.engine import make_url

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Raised when a backup, restore, verification, or delivery step fails."""


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    sha256: str
    created_at: datetime
    encrypted: bool
    telegram_sent: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["created_at"] = self.created_at.isoformat()
        return payload


def _run_command(command: list[str], *, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BackupError(f"Required command is not installed: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"Command timed out after {timeout}s: {command[0]}") from exc

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise BackupError(f"Command failed: {command[0]}: {details}")
    return result


def _postgres_cli_args(database_url: str) -> tuple[list[str], dict[str, str]]:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise BackupError("Only PostgreSQL backups are supported")
    if not url.database:
        raise BackupError("DATABASE_URL must include a database name")
    if not url.username:
        raise BackupError("DATABASE_URL must include a database user")

    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    sslmode = url.query.get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = str(sslmode)

    args = [
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username,
        "--dbname",
        url.database,
    ]
    return args, env


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encrypt_file(source: Path, destination: Path, config: Settings) -> None:
    if not config.BACKUP_ENCRYPTION_KEY:
        raise BackupError("BACKUP_ENCRYPTION_KEY is required for encryption")
    env = os.environ.copy()
    env["BACKUP_ENCRYPTION_KEY"] = config.BACKUP_ENCRYPTION_KEY
    _run_command(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-pass",
            "env:BACKUP_ENCRYPTION_KEY",
            "-in",
            str(source),
            "-out",
            str(destination),
        ],
        env=env,
        timeout=config.BACKUP_COMMAND_TIMEOUT_SECONDS,
    )


def _decrypt_file(source: Path, destination: Path, config: Settings) -> None:
    if not config.BACKUP_ENCRYPTION_KEY:
        raise BackupError("BACKUP_ENCRYPTION_KEY is required to restore encrypted backups")
    env = os.environ.copy()
    env["BACKUP_ENCRYPTION_KEY"] = config.BACKUP_ENCRYPTION_KEY
    _run_command(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-pass",
            "env:BACKUP_ENCRYPTION_KEY",
            "-in",
            str(source),
            "-out",
            str(destination),
        ],
        env=env,
        timeout=config.BACKUP_COMMAND_TIMEOUT_SECONDS,
    )


def _verify_dump(path: Path, config: Settings) -> None:
    _run_command(
        ["pg_restore", "--list", str(path)],
        env=os.environ.copy(),
        timeout=config.BACKUP_COMMAND_TIMEOUT_SECONDS,
    )


def _verify_backup_artifact(path: Path, config: Settings) -> None:
    if not config.BACKUP_VERIFY:
        return
    if path.suffix == ".enc":
        with tempfile.TemporaryDirectory(prefix="crm-backup-verify-") as temp_dir:
            decrypted = Path(temp_dir) / path.name.removesuffix(".enc")
            _decrypt_file(path, decrypted, config)
            _verify_dump(decrypted, config)
        return
    _verify_dump(path, config)


def _backup_files(output_dir: Path, prefix: str) -> list[Path]:
    files = []
    for path in output_dir.glob(f"{prefix}_*.dump*"):
        if path.name.startswith(".") or path.name.endswith(".partial"):
            continue
        if path.suffix not in {".dump", ".enc"}:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)


def prune_old_backups(output_dir: Path, config: Settings) -> None:
    files = _backup_files(output_dir, config.BACKUP_PREFIX)
    protected = set(files[: max(config.BACKUP_RETENTION_COUNT, 0)])
    cutoff = datetime.now(UTC) - timedelta(days=max(config.BACKUP_RETENTION_DAYS, 0))

    for index, path in enumerate(files):
        if path in protected:
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        should_prune_by_count = config.BACKUP_RETENTION_COUNT >= 0 and index >= config.BACKUP_RETENTION_COUNT
        should_prune_by_age = config.BACKUP_RETENTION_DAYS > 0 and modified_at < cutoff
        if should_prune_by_count or should_prune_by_age:
            path.unlink(missing_ok=True)
            logger.info("Pruned old database backup: %s", path)


def create_database_backup(
    *,
    config: Settings = settings,
    output_dir: str | Path | None = None,
    backup_name: str | None = None,
    send_to_telegram: bool = True,
) -> BackupResult:
    target_dir = Path(output_dir or config.BACKUP_STORAGE_PATH)
    target_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(UTC)
    stem = backup_name or f"{config.BACKUP_PREFIX}_{created_at.strftime('%Y%m%d_%H%M%S_UTC')}"
    raw_path = target_dir / f"{stem}.dump"
    final_path = target_dir / f"{stem}.dump.enc" if config.BACKUP_ENCRYPTION_KEY else raw_path
    raw_partial = target_dir / f".{raw_path.name}.partial"
    final_partial = target_dir / f".{final_path.name}.partial"

    for stale_path in (raw_partial, final_partial):
        stale_path.unlink(missing_ok=True)

    pg_args, env = _postgres_cli_args(config.DATABASE_URL)
    logger.info("Creating PostgreSQL backup: %s", final_path)
    _run_command(
        [
            "pg_dump",
            *pg_args,
            "--format=custom",
            "--compress=9",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(raw_partial),
        ],
        env=env,
        timeout=config.BACKUP_COMMAND_TIMEOUT_SECONDS,
    )

    if config.BACKUP_ENCRYPTION_KEY:
        _encrypt_file(raw_partial, final_partial, config)
        raw_partial.unlink(missing_ok=True)
        final_partial.replace(final_path)
    else:
        raw_partial.replace(final_path)

    _verify_backup_artifact(final_path, config)
    result = BackupResult(
        path=final_path,
        size_bytes=final_path.stat().st_size,
        sha256=_sha256(final_path),
        created_at=created_at,
        encrypted=bool(config.BACKUP_ENCRYPTION_KEY),
    )

    if send_to_telegram and telegram_delivery_configured(config):
        send_backup_to_telegram(result, config=config)
        result.telegram_sent = True

    prune_old_backups(target_dir, config)
    logger.info(
        "Database backup ready: path=%s size=%s sha256=%s telegram_sent=%s",
        result.path,
        result.size_bytes,
        result.sha256,
        result.telegram_sent,
    )
    return result


def restore_database_backup(
    backup_path: str | Path,
    *,
    config: Settings = settings,
    database_url: str | None = None,
    clean: bool = True,
) -> None:
    source = Path(backup_path)
    if not source.exists():
        raise BackupError(f"Backup file does not exist: {source}")

    pg_args, env = _postgres_cli_args(database_url or config.DATABASE_URL)
    with tempfile.TemporaryDirectory(prefix="crm-backup-restore-") as temp_dir:
        restore_source = source
        if source.suffix == ".enc":
            restore_source = Path(temp_dir) / source.name.removesuffix(".enc")
            _decrypt_file(source, restore_source, config)

        _verify_dump(restore_source, config)
        command = [
            "pg_restore",
            *pg_args,
            "--no-owner",
            "--no-privileges",
        ]
        if clean:
            command.extend(["--clean", "--if-exists"])
        command.append(str(restore_source))
        _run_command(command, env=env, timeout=config.BACKUP_COMMAND_TIMEOUT_SECONDS)


def telegram_delivery_configured(config: Settings = settings) -> bool:
    return bool(config.BACKUP_TELEGRAM_BOT_TOKEN and config.BACKUP_TELEGRAM_CHAT_ID)


def _telegram_method_url(method: str, config: Settings) -> str:
    base_url = config.BACKUP_TELEGRAM_API_BASE_URL.rstrip("/")
    return f"{base_url}/bot{config.BACKUP_TELEGRAM_BOT_TOKEN}/{method}"


def send_telegram_message(text: str, *, config: Settings = settings) -> None:
    if not telegram_delivery_configured(config):
        return
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = client.post(
            _telegram_method_url("sendMessage", config),
            json={
                "chat_id": config.BACKUP_TELEGRAM_CHAT_ID,
                "text": text[:4096],
                "disable_web_page_preview": True,
            },
        )
        if response.status_code >= 400:
            raise BackupError(f"Telegram sendMessage failed: HTTP {response.status_code}: {response.text}")
        payload = response.json()
        if not payload.get("ok"):
            raise BackupError(f"Telegram sendMessage failed: {payload}")


def send_backup_to_telegram(result: BackupResult, *, config: Settings = settings) -> None:
    if not telegram_delivery_configured(config):
        return

    max_upload_bytes = config.BACKUP_TELEGRAM_MAX_UPLOAD_MB * 1024 * 1024
    if result.size_bytes > max_upload_bytes:
        message = (
            "Database backup was created locally but was not sent to Telegram: "
            f"{result.path.name} is {result.size_bytes / 1024 / 1024:.1f} MB, "
            f"limit is {config.BACKUP_TELEGRAM_MAX_UPLOAD_MB} MB."
        )
        send_telegram_message(message, config=config)
        raise BackupError(message)

    caption = (
        f"CRM database backup\n"
        f"file: {result.path.name}\n"
        f"size: {result.size_bytes / 1024 / 1024:.1f} MB\n"
        f"sha256: {result.sha256[:16]}\n"
        f"encrypted: {'yes' if result.encrypted else 'no'}"
    )

    timeout = httpx.Timeout(float(config.BACKUP_TELEGRAM_TIMEOUT_SECONDS), connect=30.0)
    with result.path.open("rb") as file, httpx.Client(timeout=timeout) as client:
        response = client.post(
            _telegram_method_url("sendDocument", config),
            data={
                "chat_id": config.BACKUP_TELEGRAM_CHAT_ID,
                "caption": caption[:1024],
            },
            files={
                "document": (
                    result.path.name,
                    file,
                    "application/octet-stream",
                ),
            },
        )
    if response.status_code >= 400:
        raise BackupError(f"Telegram sendDocument failed: HTTP {response.status_code}: {response.text}")
    payload = response.json()
    if not payload.get("ok"):
        raise BackupError(f"Telegram sendDocument failed: {payload}")


def ensure_required_backup_tools() -> None:
    missing = [tool for tool in ("pg_dump", "pg_restore", "openssl") if not shutil.which(tool)]
    if missing:
        raise BackupError(f"Missing required backup tools: {', '.join(missing)}")
