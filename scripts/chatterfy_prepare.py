"""Prepare a private import report/mapping template from an existing archive. No network or DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chatterfy_export_service import ChatterfyExportError, DEFAULT_START, write_private_json
from app.services.chatterfy_import_service import archive_report, prepare_chat, source_requires_mapping


def load_archive(directories: list[Path], *, source_bot_id: str, source_username: str,
                 created_from: str = DEFAULT_START):
    items, originals, total_bytes, total_records = {}, {}, 0, 0
    for directory in directories:
        if not directory.is_dir() or directory.stat().st_mode & 0o077:
            raise ChatterfyExportError("Archive directories must be private (permissions 700)")
        for file in sorted(directory.glob("*.json")):
            if not file.is_file() or file.is_symlink() or file.stat().st_size > 64 * 1024 * 1024 or file.stat().st_mode & 0o077:
                raise ChatterfyExportError("Unsafe archive file; require regular private JSON files up to 64 MiB")
            total_bytes += file.stat().st_size
            if total_bytes > 128 * 1024 * 1024:
                raise ChatterfyExportError("Batch exceeds 128 MiB; split the archive into bounded batches")
            value = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or "chat" not in value:
                continue
            item = prepare_chat(value, source_bot_id=source_bot_id, source_username=source_username, created_from=created_from)
            total_records += len(value["messages"])
            if len(items) >= 2000 or total_records > 100000:
                raise ChatterfyExportError("Batch limit reached (2000 chats / 100000 messages); split the archive")
            prior = items.get(item.source_chat_id)
            if prior and prior.provenance["archive_digest"] != item.provenance["archive_digest"]:
                raise ChatterfyExportError("Conflicting chat snapshots; select a single verified snapshot")
            items[item.source_chat_id] = item
            originals[item.source_chat_id] = {"file": str(file.resolve()), "digest": item.provenance["archive_digest"]}
    if not items:
        raise ChatterfyExportError("No complete chat envelopes in the supplied archive")
    result = sorted(items.values(), key=lambda c: c.source_chat_id)
    archive_report(result)  # Also validates cross-chat Telegram identity uniqueness.
    return result, originals


def mapping_template(items, *, source_bot_id: str, source_username: str, created_from: str):
    report = archive_report(items)
    proposals = []
    for source in report["sources"]:
        if not source_requires_mapping(source):
            continue
        old_payload = "t_" + source["source_id"]
        proposals.append({"source_key": source["key"],
            "name": "Chatterfy · " + source["source_id"],
            "code": "chf_" + hashlib.sha256(source["key"].encode()).hexdigest()[:20],
            "observed_legacy_payload": old_payload if old_payload in source["observed_start_payloads"] else None})
    return {"schema": 1, "source_bot_id": source_bot_id, "source_username": source_username.lstrip("@"),
        "created_from": created_from, "destination": {"project_id": None, "bot_id": None, "status_id": None},
        "tag_map": {key: None for key in report["source_tag_ids"]},
        "source_map": {source["key"]: None for source in report["sources"] if source_requires_mapping(source)},
        "link_proposals": proposals, "resume_mode": "manual_only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, action="append", required=True)
    parser.add_argument("--source-bot-id", required=True)
    parser.add_argument("--source-username", required=True)
    parser.add_argument("--created-from", default=DEFAULT_START)
    parser.add_argument("--tags-file", type=Path, help="Private GET /bots/v1/{id}/tags response for source names")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        items, originals = load_archive(args.archive_dir, source_bot_id=args.source_bot_id,
            source_username=args.source_username, created_from=args.created_from)
        report = archive_report(items)
        mapping = mapping_template(items, source_bot_id=args.source_bot_id,
            source_username=args.source_username, created_from=args.created_from)
        if args.tags_file:
            if args.tags_file.stat().st_mode & 0o077:
                raise ChatterfyExportError("Tag dictionary must be private")
            dictionary = json.loads(args.tags_file.read_text())
            if (not isinstance(dictionary, dict) or not isinstance(dictionary.get("data"), list)
                    or not isinstance(dictionary.get("pagination"), dict)
                    or dictionary["pagination"].get("has_more") is not False):
                raise ChatterfyExportError("Tag dictionary must be completely paginated")
            if any(not isinstance(row, dict) or row.get("bot_id") != args.source_bot_id
                   or not isinstance(row.get("id"), str) or not isinstance(row.get("name"), str)
                   for row in dictionary["data"]):
                raise ChatterfyExportError("Tag dictionary contains a different bot")
            mapping["source_tag_names"] = {row["id"]: row["name"] for row in dictionary["data"]}
        args.output.mkdir(mode=0o700, exist_ok=False)
        write_private_json(args.output / "report.json", report)
        write_private_json(args.output / "archive-index.json", originals)
        write_private_json(args.output / "mapping-template.json", mapping)
        print(json.dumps({key: report[key] for key in ("mode", "chats", "delivered_history_records", "warnings", "crm_writes")}))
        return 0
    except (ChatterfyExportError, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ChatterfyExportError) else "Check private input files and a new output directory"
        print(f"Preparation stopped: {message}. No CRM writes.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
