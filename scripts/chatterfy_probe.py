"""Discover Chatterfy bots or export a read-only sample; never import into CRM."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chatterfy_export_service import (
    ChatterfyExportError, ChatterfyReadClient, DEFAULT_START, probe_chats, write_private_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private directory; never reused or overwritten")
    parser.add_argument("--bot-id", help="Omit to discover source bots first")
    parser.add_argument("--expected-username", help="Required with --bot-id; exact source bot safety check")
    parser.add_argument("--created-from", default=DEFAULT_START)
    parser.add_argument("--sample-size", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--max-message-pages", type=int, default=100)
    args = parser.parse_args()
    client = None
    try:
        if args.api_key_file.stat().st_mode & 0o077:
            raise ChatterfyExportError("API key file must be private (permissions 600)")
        key = args.api_key_file.read_text(encoding="utf-8").strip()
        if args.max_message_pages < 1:
            raise ChatterfyExportError("Message page limit must be positive")
        if args.bot_id and not args.expected_username:
            raise ChatterfyExportError("Provide --expected-username to verify the source before reading chats")
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        client = ChatterfyReadClient(key)
        if args.bot_id:
            report = probe_chats(client, args.output, bot_id=args.bot_id, start=args.created_from,
                                 sample_size=args.sample_size, max_message_pages=args.max_message_pages,
                                 expected_username=args.expected_username)
            print(json.dumps({k: report[k] for k in ("mode", "matching_chats_reported", "sample_chats", "requests", "crm_writes")}))
        else:
            bots = client.discover()
            write_private_json(args.output / "bots.json", bots)
            print(json.dumps({"mode": "read_only_discovery", "bots": len(bots), "crm_writes": 0}))
        return 0
    except ChatterfyExportError as exc:
        print(f"Probe stopped: {exc}. No CRM writes; partial output is not a complete export.", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Probe stopped: check private key file and new output directory. No CRM writes.", file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
