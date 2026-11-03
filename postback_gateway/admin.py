"""Local-only queue operations; never expose these as public HTTP endpoints."""
import argparse
import json
from .config import Config
from .queue import Queue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["stats", "dead", "retry", "backup"])
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    queue = Queue(Config.from_env())
    if args.action == "stats":
        print(json.dumps(queue.stats(), indent=2))
    elif args.action == "dead":
        with queue.connect() as db:
            rows = db.execute("SELECT id,created,attempts,error FROM jobs WHERE status='dead' ORDER BY created LIMIT 100").fetchall()
            print(json.dumps([dict(row) for row in rows], indent=2))
    elif args.action == "retry":
        if not args.value:
            parser.error("Delivery ID required")
        print(json.dumps({"requeued": queue.retry(args.value)}))
    else:
        import os
        from pathlib import Path
        import sqlite3
        if not args.value:
            parser.error("Backup destination path required")
        destination = Path(args.value)
        partial = Path(str(destination) + ".partial")
        if destination.exists():
            parser.error("Backup destination already exists")
        fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with queue.connect() as db:
                target = sqlite3.connect(partial)
                try:
                    db.backup(target)
                finally:
                    target.close()
            os.link(partial, destination)
        finally:
            partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
