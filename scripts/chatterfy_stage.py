"""Check/apply explicitly mapped text-only history to an offline bot draft. Never switches webhook."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chatterfy_export_service import ChatterfyExportError
from app.services.chatterfy_import_service import ChatterfyStagingImporter, create_staging_links
from scripts.chatterfy_prepare import load_archive


async def run(args):
    if args.mapping.stat().st_mode & 0o077:
        raise ChatterfyExportError("Mapping must be private (permissions 600)")
    config = json.loads(args.mapping.read_text())
    if config.get("schema") != 1 or config.get("resume_mode") != "manual_only":
        raise ChatterfyExportError("Only schema 1 manual-only imports are supported")
    destination = config["destination"]
    project_id, bot_id, status_id = (UUID(destination[key]) for key in ("project_id", "bot_id", "status_id"))
    if args.apply and args.confirm_bot_id != str(bot_id):
        raise ChatterfyExportError("An apply requires repeating the exact destination bot UUID")
    if args.create_links and not args.apply:
        raise ChatterfyExportError("Creating links requires explicit --apply and --confirm-bot-id")
    items, _ = load_archive(args.archive_dir, source_bot_id=config["source_bot_id"],
        source_username=config["source_username"], created_from=config["created_from"])
    # Load the DB configuration only after offline validation and explicit selection.
    from sqlalchemy import text
    from app.core.database import get_db_session, engine
    try:
        async with get_db_session() as db:
            if not args.apply:
                await db.execute(text("SET TRANSACTION READ ONLY"))
            sources = {key: UUID(value) for key, value in config["source_map"].items() if value}
            if args.create_links:
                sources.update({key: UUID(value) for key, value in (await create_staging_links(db,
                    project_id=project_id, bot_id=bot_id, proposals=config["link_proposals"])).items()})
            importer = ChatterfyStagingImporter(db, project_id=project_id, bot_id=bot_id,
                source_bot_id=config["source_bot_id"], source_username=config["source_username"], status_id=status_id,
                tag_map={key: UUID(value) for key, value in config["tag_map"].items() if value}, source_map=sources)
            # Validate ALL selected chats before the first commit. A media/conflict failure
            # must not create links or partially import an otherwise invalid batch.
            for item in items:
                await importer.import_chat(item, dry_run=True)
            if not args.apply:
                await db.rollback()
                print(json.dumps({"mode": "read_only_preflight", "ready": len(items), "crm_writes": 0}))
                return
            counts = {}
            for item in items:
                result = await importer.import_chat(item, dry_run=False)
                await db.commit()
                counts[result["status"]] = counts.get(result["status"], 0) + 1
            print(json.dumps({"mode": "staging_only", "chats": counts, "source_map": {k: str(v) for k, v in sources.items()},
                              "telegram_sends": 0, "webhook_changes": 0}))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, action="append", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-bot-id")
    parser.add_argument("--create-links", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
        return 0
    except Exception as exc:
        # Database exceptions can include private message text in SQL parameters.
        detail = str(exc) if isinstance(exc, ChatterfyExportError) else type(exc).__name__
        print(f"Staging stopped: {detail}. Previously committed chats are retained; rerun is idempotent.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
