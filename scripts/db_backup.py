from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backup_service import BackupError, create_database_backup, ensure_required_backup_tools


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a verified PostgreSQL database backup.")
    parser.add_argument("--output-dir", type=Path, help="Directory for the backup file.")
    parser.add_argument("--name", help="Backup file stem without extension.")
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Create the local backup but skip Telegram delivery even if configured.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ensure_required_backup_tools()
        result = create_database_backup(
            output_dir=args.output_dir,
            backup_name=args.name,
            send_to_telegram=not args.no_telegram,
        )
    except BackupError as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"Backup created: {result.path}")
    print(f"Size: {result.size_bytes / 1024 / 1024:.1f} MB")
    print(f"SHA256: {result.sha256}")
    print(f"Encrypted: {'yes' if result.encrypted else 'no'}")
    print(f"Telegram sent: {'yes' if result.telegram_sent else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
