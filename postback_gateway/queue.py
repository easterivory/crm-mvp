"""Local durable inbox. No CRM credentials or database access are required."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from uuid import uuid4


class IntakeError(Exception):
    def __init__(self, status):
        self.status = status


class Queue:
    def __init__(self, config):
        self.config = config
        self.path = Path(config.database)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS allowed (hash TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, payload BLOB NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL, due REAL NOT NULL,
                    lease REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT, result TEXT);
                CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status, due);
                CREATE INDEX IF NOT EXISTS jobs_updated ON jobs(status, updated);
            """)
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('instance_id', ?)", (str(uuid4()),))
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def set_manifest(self, hashes, entries=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM allowed")
            db.executemany("INSERT INTO allowed(hash) VALUES (?)", [(h,) for h in set(hashes)])
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('manifest_at', ?)", (str(time.time()),))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('manifest_entries', ?)", (json.dumps(entries or {}),))

    def _admit(self, db, token):
        row = db.execute("SELECT value FROM metadata WHERE key='manifest_at'").fetchone()
        if not row or time.time() - float(row[0]) > self.config.manifest_ttl:
            raise IntakeError(503)
        if not db.execute("SELECT 1 FROM allowed WHERE hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone():
            raise IntakeError(404)

    def check_token(self, token):
        with self.connect() as db:
            self._admit(db, token)

    def enqueue(self, token, method, query, body, *, include_ack=False):
        if shutil.disk_usage(self.path.parent).free < self.config.min_free_bytes:
            raise IntakeError(503)
        delivery_id = str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._admit(db, token)
            metadata = db.execute("SELECT value FROM metadata WHERE key='manifest_entries'").fetchone()
            entry = json.loads(metadata[0]).get(hashlib.sha256(token.encode()).hexdigest()) if metadata else None
            extra = {"received_at": datetime.now(timezone.utc).isoformat(), "endpoint_id": entry["endpoint_id"],
                "endpoint_revision": entry["revision"]} if entry else {}
            payload = json.dumps(dict(delivery_id=delivery_id, secret_token=token, request_method=method,
                query_payload=query, body_payload=body, **extra), ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
            if len(payload) > 262144:
                raise IntakeError(413)
            if db.execute("SELECT count(*) FROM jobs WHERE status != 'done'").fetchone()[0] >= self.config.max_jobs:
                raise IntakeError(503)
            stamp = time.time()
            db.execute("INSERT INTO jobs(id,payload,status,created,updated,due) VALUES (?,?,'pending',?,?,?)",
                (delivery_id, payload, stamp, stamp, stamp))
        return (delivery_id, entry.get("ack_text") if entry else None) if include_ack else delivery_id

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            stamp = time.time()
            db.execute("UPDATE jobs SET status='pending' WHERE status='sending' AND lease < ?", (stamp,))
            row = db.execute("SELECT * FROM jobs WHERE status='pending' AND due <= ? ORDER BY due,id LIMIT 1", (stamp,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='sending',lease=?,attempts=attempts+1,updated=? WHERE id=?",
                (stamp + 120, stamp, row["id"]))
            return dict(row)

    def finish(self, delivery_id, status, *, delay=0, error=None, result=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?,due=?,lease=0,updated=?,error=?,result=? WHERE id=?",
                (status, time.time() + delay, time.time(), error, result, delivery_id))

    def prune(self):
        # Failed/pending jobs are never automatically deleted.
        with self.connect() as db:
            db.execute("DELETE FROM jobs WHERE status='done' AND updated < ?", (time.time() - 7 * 86400,))

    def stats(self):
        with self.connect() as db:
            counts = dict(db.execute("SELECT status,count(*) FROM jobs GROUP BY status").fetchall())
            oldest = db.execute("SELECT min(created) FROM jobs WHERE status IN ('pending','sending')").fetchone()[0]
            manifest = db.execute("SELECT value FROM metadata WHERE key='manifest_at'").fetchone()
            return {"counts": counts, "oldest_pending_seconds": max(0, time.time() - oldest) if oldest else 0,
                "instance_id": db.execute("SELECT value FROM metadata WHERE key='instance_id'").fetchone()[0],
                "manifest_age_seconds": max(0, time.time() - float(manifest[0])) if manifest else None,
                "free_bytes": shutil.disk_usage(self.path.parent).free}

    def retry(self, delivery_id):
        with self.connect() as db:
            # Reuse the transport ID. Never manufacture a second business event.
            return db.execute("UPDATE jobs SET status='pending',due=?,error=NULL WHERE id=? AND status='dead'",
                (time.time(), delivery_id)).rowcount
