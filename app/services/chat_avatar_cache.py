"""Bounded, disposable thumbnail cache shared by API processes."""
from __future__ import annotations

import asyncio
import io
import sqlite3
import time
from pathlib import Path

from PIL import Image, ImageOps

MAX_THUMBNAIL_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def avatar_thumbnail(content: bytes) -> bytes:
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise ValueError("Avatar source exceeds limit")
    with Image.open(io.BytesIO(content)) as image:
        if image.width * image.height > 4_000_000:
            raise ValueError("Avatar dimensions exceed limit")
        image.seek(0)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((128, 128))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=80, optimize=True)
    result = output.getvalue()
    if len(result) > MAX_THUMBNAIL_BYTES:
        raise ValueError("Avatar thumbnail exceeds limit")
    return result


class ChatAvatarCache:
    def __init__(self, path: Path, *, max_bytes: int, max_entries: int = 10000):
        self.path = path
        self.max_bytes = max(max_bytes, 64 * 1024)
        self.max_entries = max(1, max_entries)

    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2)
        connection.execute("PRAGMA journal_mode=DELETE")
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={max(16, self.max_bytes // page_size)}")
        connection.execute("PRAGMA cache_size=-512")
        connection.execute("CREATE TABLE IF NOT EXISTS avatars "
                           "(key TEXT PRIMARY KEY, content BLOB, expires REAL NOT NULL, accessed REAL NOT NULL)")
        connection.execute("CREATE INDEX IF NOT EXISTS avatars_accessed ON avatars(accessed)")
        return connection

    async def get(self, key: str) -> tuple[bytes | None, bool] | None:
        def read():
            connection = self._connection()
            try:
                with connection:
                    now = time.time()
                    connection.execute("DELETE FROM avatars WHERE accessed < ?", (now - 30 * 86400,))
                    row = connection.execute("SELECT content, expires, accessed FROM avatars WHERE key=?", (key,)).fetchone()
                    if row is None:
                        return None
                    if row[2] < now - 30 * 86400:
                        connection.execute("DELETE FROM avatars WHERE key=?", (key,))
                        return None
                    connection.execute("UPDATE avatars SET accessed=? WHERE key=?", (now, key))
                    return row[0], row[1] > now
            finally:
                connection.close()
        return await asyncio.to_thread(read)

    async def put(self, key: str, content: bytes | None, *, ttl: int) -> None:
        if content is not None and len(content) > min(MAX_THUMBNAIL_BYTES, self.max_bytes // 2):
            raise ValueError("Avatar thumbnail exceeds limit")
        def write():
            connection = self._connection()
            try:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    now = time.time()
                    connection.execute("DELETE FROM avatars WHERE accessed < ?", (now - 30 * 86400,))
                    connection.execute("DELETE FROM avatars WHERE key=?", (key,))
                    # Leave room for SQLite indexes/pages and reuse freed pages;
                    # max_page_count also puts a hard ceiling on the database file.
                    budget = self.max_bytes // 2
                    while True:
                        count, size = connection.execute(
                            "SELECT count(*), coalesce(sum(length(content)), 0) FROM avatars"
                        ).fetchone()
                        if count < self.max_entries and size + len(content or b"") <= budget:
                            break
                        batch = max(1, count - self.max_entries + 1) if count >= self.max_entries else 64
                        connection.execute("DELETE FROM avatars WHERE key IN "
                                           "(SELECT key FROM avatars ORDER BY accessed LIMIT ?)", (batch,))
                    connection.execute("INSERT INTO avatars VALUES (?, ?, ?, ?)",
                                       (key, content, now + ttl, now))
            finally:
                connection.close()
        await asyncio.to_thread(write)
