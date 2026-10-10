"""Disposable, bounded ZIP archives containing UTF-8 chat transcripts."""
import json
import os
import shutil
import time
import zipfile
from pathlib import Path
from uuid import UUID

from app.core.config import settings

EXPORT_TTL = 24 * 60 * 60


def export_directory() -> Path:
    return Path(settings.CHAT_ATTACHMENT_STORAGE_PATH) / "dialog_exports"


def cleanup_exports() -> None:
    directory = export_directory()
    if not directory.exists():
        return
    for path in directory.glob("*/*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < time.time() - EXPORT_TTL:
            if path.suffix in {".zip", ".partial"}:
                path.unlink(missing_ok=True)


def export_path(project_id: UUID, export_id: UUID, *, partial: bool = False) -> Path:
    return export_directory() / str(project_id) / f"{export_id}{'.partial' if partial else '.zip'}"


def resolve_export(project_id: UUID, export_id: UUID) -> Path:
    path = export_path(project_id, export_id)
    if path.is_symlink() or not path.is_file() or path.stat().st_mtime < time.time() - EXPORT_TTL:
        raise FileNotFoundError("Export expired")
    return path


class ExportLimitError(ValueError):
    pass


class DialogArchive:
    def __init__(self, project_id: UUID, export_id: UUID, manifest: dict):
        cleanup_exports()
        self.path = export_path(project_id, export_id, partial=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        quota = max(1, settings.DIALOG_EXPORT_STORAGE_MAX_MB) * 1024 * 1024
        used = sum(path.stat().st_size for path in export_directory().glob("*/*") if path.is_file())
        if used >= quota or shutil.disk_usage(self.path.parent).free < 512 * 1024 * 1024:
            raise ExportLimitError("Недостаточно места для экспорта. Удалите старые выгрузки или увеличьте лимит хранения.")
        self.available = quota - used
        self.limit = min(max(1, settings.DIALOG_EXPORT_MAX_MB) * 1024 * 1024, self.available)
        self.part_limit = max(1, settings.DIALOG_EXPORT_PART_MB) * 1024 * 1024
        self.manifest = manifest
        self.format = manifest["request"]["format"]
        self.archive = zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3)
        os.chmod(self.path, 0o600)
        self.part = None
        self.part_bytes = 0
        self.total_bytes = 0
        self.parts = []
        self.context = None

    def _write(self, content: bytes) -> None:
        if self.total_bytes + len(content) > self.limit:
            raise ExportLimitError("Выгрузка слишком большая. Выберите бота или сократите период сообщений.")
        self.part.write(content)
        self.part_bytes += len(content)
        self.total_bytes += len(content)

    def _new_part(self, *, repeat_context: bool = True) -> None:
        if self.part is not None:
            self.part.close()
        name = f"dialogs_{len(self.parts) + 1:04d}.{self.format}"
        self.parts.append(name)
        self.part = self.archive.open(name, "w", force_zip64=True)
        self.part_bytes = 0
        header = {"type": "export", **self.manifest}
        self._write(self.encode(header))
        if repeat_context and self.context is not None:
            self._write(self.encode(self.context))

    def encode(self, record: dict) -> bytes:
        if self.format == "jsonl":
            text = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        elif record["type"] == "chat":
            text = "\n=== ДИАЛОГ ===\n" + json.dumps(record, ensure_ascii=False, default=str) + "\n"
        elif record["type"] == "message":
            attachment = record.get("attachment")
            suffix = f"\n[Вложение: {json.dumps(attachment, ensure_ascii=False)}]" if attachment else ""
            flags = " [удалено]" if record.get("deleted_at") else " [изменено]" if record.get("edited_at") else ""
            text = (f"[{record['created_at']}] {record['sender_type']} ({record.get('author') or '-'}){flags} "
                    f"id={record['id']} reply_to={record.get('reply_to_message_id') or '-'}\n"
                    f"{record.get('text') or ''}{suffix}\n")
            for key, label in (("original_text", "Исходный текст"), ("translated_text", "Перевод")):
                if record.get(key) and record[key] != record.get("text"):
                    text += f"[{label}] {record[key]}\n"
            if record.get("buttons"):
                text += "[Кнопки] " + " | ".join(record["buttons"]) + "\n"
        else:
            text = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        return text.encode("utf-8")

    def write_records(self, records: list[dict]) -> None:
        if shutil.disk_usage(self.path.parent).free < 64 * 1024 * 1024:
            raise ExportLimitError("Недостаточно свободного места для выгрузки.")
        for record in records:
            if self.part is None:
                self._new_part()
            content = self.encode(record)
            if self.part_bytes + len(content) > self.part_limit:
                self._new_part(repeat_context=record['type'] != 'chat')
            self._write(content)
            if record["type"] == "chat":
                self.context = record
        self.archive.fp.flush()
        if self.path.stat().st_size > self.available:
            raise ExportLimitError("Превышен лимит хранения выгрузок.")

    def finish(self, stats: dict) -> Path:
        if self.part is None:
            self._new_part()
        self.part.close()
        self.part = None
        self.archive.writestr("manifest.json", json.dumps({**self.manifest, **stats, "parts": self.parts}, ensure_ascii=False, indent=2))
        self.archive.close()
        if self.path.stat().st_size > self.available:
            raise ExportLimitError("Превышен лимит хранения выгрузок.")
        final = self.path.with_suffix(".zip")
        self.path.replace(final)
        return final

    def abort(self) -> None:
        if self.part is not None:
            self.part.close()
        self.archive.close()
        self.path.unlink(missing_ok=True)
        self.path.with_suffix('.zip').unlink(missing_ok=True)
