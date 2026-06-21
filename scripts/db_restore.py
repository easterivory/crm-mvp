from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backup_service import BackupError, ensure_required_backup_tools, restore_database_backup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL database backup.")
    parser.add_argument("backup_file", type=Path, help="Path to .dump or .dump.enc backup file.")
    parser.add_argument(
        "--database-url",
        help="Override target database URL. Defaults to DATABASE_URL from .env.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not pass --clean/--if-exists to pg_restore.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm that the target database may be overwritten.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.yes:
        print(
            "Restore refused: pass --yes after stopping API/worker containers and verifying the target DATABASE_URL.",
            file=sys.stderr,
        )
        return 2

    try:
        ensure_required_backup_tools()
        restore_database_backup(
            args.backup_file,
            database_url=args.database_url,
            clean=not args.no_clean,
        )
    except BackupError as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1

    print(f"Restore completed from: {args.backup_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
