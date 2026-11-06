"""Read-only Chatterfy Public API probe. No CRM/database/Telegram dependencies."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import httpx

API_BASE = "https://api.chatterfy.ai/public-api"
READ_PATHS = frozenset({"/companies/v1/search", "/bots/v1/search", "/chats/v1/stats",
                        "/chats/v1/export", "/messages/v1/search"})
DEFAULT_START = "2026-08-01T00:00:00+03:00"


class ChatterfyExportError(RuntimeError):
    pass


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ChatterfyExportError("Missing or invalid source timestamp") from None
    if result.tzinfo is None:
        raise ChatterfyExportError("Source timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def created_filter(start: str, end: str) -> dict:
    lower, upper = timestamp(start), timestamp(end)
    if lower > upper:
        raise ChatterfyExportError("Start must not be later than the snapshot cutoff")
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    return {"field": "created_at", "operator": "between", "value": [iso(lower), iso(upper)]}


class ChatterfyReadClient:
    def __init__(self, key: str, *, transport=None, sleep=time.sleep, clock=time.monotonic,
                 interval: float = 0.6, max_requests: int = 1000):
        if not key or len(key.splitlines()) != 1 or len(key) > 4096:
            raise ChatterfyExportError("API key file must contain one non-empty key line")
        self.http = httpx.Client(headers={"ApiKey": key}, timeout=30, follow_redirects=False,
                                 trust_env=False, transport=transport)
        self.sleep, self.clock, self.interval = sleep, clock, interval
        self.max_requests, self.requests = max_requests, 0
        self.last_request = None

    def close(self):
        self.http.close()

    def call(self, path: str, body: dict) -> dict:
        if path not in READ_PATHS:
            raise ChatterfyExportError("Only documented read/export operations are permitted")
        return self._read("POST", path, body)

    def metadata(self, path: str, params: dict | None = None) -> dict:
        identifier = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        if not re.fullmatch(rf"/(?:bots/v1/{identifier}/(?:tags|custom-fields)|campaigns/v1/{identifier})", path):
            raise ChatterfyExportError("Only documented metadata reads are permitted")
        if params and (set(params) - {"limit", "cursor"} or type(params.get("limit", 100)) is not int
                       or not 1 <= params.get("limit", 100) <= 100
                       or ("cursor" in params and not isinstance(params["cursor"], str))):
            raise ChatterfyExportError("Only metadata pagination parameters are permitted")
        return self._read("GET", path, None, params=params)

    def _read(self, method: str, path: str, body: dict | None, *, params: dict | None = None) -> dict:
        for attempt in range(4):
            if self.requests >= self.max_requests:
                raise ChatterfyExportError("Request budget exceeded; probe is incomplete")
            if self.last_request is not None:
                self.sleep(max(0, self.interval - (self.clock() - self.last_request)))
            self.requests += 1
            self.last_request = self.clock()
            try:
                response = self.http.request(method, API_BASE + path, params=params,
                                             **({"json": body} if body is not None else {}))
            except httpx.TransportError:
                if attempt == 3:
                    raise ChatterfyExportError("Public API transport failure after bounded retries") from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 3:
                    raise ChatterfyExportError(f"Public API unavailable: HTTP {response.status_code}")
                try:
                    delay = float(response.headers.get("Retry-After", 2 ** attempt))
                except ValueError:
                    raise ChatterfyExportError("Non-numeric Retry-After; stop and retry later") from None
                if not 0 <= delay <= 30:
                    raise ChatterfyExportError("Server requested a long cooldown; stop and retry later")
                self.sleep(delay)
                continue
            if response.status_code != 200:
                # Never echo a response body, URL or exception that might contain a key/PII.
                raise ChatterfyExportError(f"Public API rejected read: HTTP {response.status_code}")
            try:
                data = response.json()
            except ValueError:
                raise ChatterfyExportError("Public API did not return JSON") from None
            if not isinstance(data, dict) or data.get("error") is not None:
                raise ChatterfyExportError("Public API returned an error or an unknown response envelope")
            return data
        raise AssertionError("Unreachable")

    def pages(self, path: str, body: dict, *, max_pages: int = 100, metadata: bool = False) -> Iterator[list[dict]]:
        cursor, seen = None, set()
        for _ in range(max_pages):
            params = {**body, **({"cursor": cursor} if cursor is not None else {})}
            page = self.metadata(path, params) if metadata else self.call(path, params)
            rows, pagination = page.get("data"), page.get("pagination")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ChatterfyExportError("Invalid page data; do not assume an empty export")
            if not isinstance(pagination, dict) or type(pagination.get("has_more")) is not bool:
                raise ChatterfyExportError("Missing pagination; export completeness cannot be established")
            has_more, next_cursor = pagination["has_more"], pagination.get("next_cursor")
            if has_more and (not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen):
                raise ChatterfyExportError("Missing or repeating cursor; export is incomplete")
            yield rows
            if not has_more:
                return
            seen.add(next_cursor)
            cursor = next_cursor
        raise ChatterfyExportError("Page limit reached; export is incomplete")

    def discover(self) -> list[dict]:
        bots = {}
        for page in self.pages("/companies/v1/search", {}, max_pages=20):
            for company in page:
                company_id = source_id(company)
                for bot_page in self.pages("/bots/v1/search", {"company_id": company_id}, max_pages=100):
                    for bot in bot_page:
                        # Do not write arbitrary bot fields (including possible credentials).
                        bots[source_id(bot)] = {key: bot.get(key) for key in ("id", "name", "username", "space_id", "status", "access")}
        return list(bots.values())


def source_id(row: dict) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ChatterfyExportError("Source row has no stable ID")
    return value


def write_private_json(path: Path, value) -> None:
    with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
        json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")


def read_chat_history(client: ChatterfyReadClient, chat: dict, *, expected_bot_id: str,
                      max_message_pages: int = 100, page_size: int = 100) -> tuple[list[dict], int]:
    if chat.get("bot_id") != expected_bot_id:
        raise ChatterfyExportError("Chat does not belong to the verified bot")
    if not 1 <= page_size <= 100:
        raise ChatterfyExportError("Message page size must be between 1 and 100")
    cid = source_id(chat)
    messages, pages = {}, 0
    for rows in client.pages("/messages/v1/search", {"chat_id": cid, "limit": page_size, "order": "asc", "type": "message"},
                             max_pages=max_message_pages):
        pages += 1
        for message in rows:
            mid = source_id(message)
            if message.get("chat_id") != cid or message.get("type") != "message":
                raise ChatterfyExportError("Messages do not belong to the requested chat/type")
            timestamp(message.get("created_at"))
            if message.get("sender_type") not in {"incoming", "outcoming"}:
                raise ChatterfyExportError("Unknown sender type; do not guess message authors")
            files = message.get("files") or []
            if not isinstance(files, list) or any(not isinstance(file, dict) for file in files):
                raise ChatterfyExportError("Unknown media metadata schema; inspect before importing")
            if mid in messages and messages[mid] != message:
                raise ChatterfyExportError("Message changed between pages; rerun the probe")
            messages[mid] = message
    return sorted(messages.values(), key=lambda row: (timestamp(row["created_at"]), row["id"])), pages


def probe_chats(client: ChatterfyReadClient, output: Path, *, bot_id: str, start: str = DEFAULT_START,
                end: str | None = None, sample_size: int = 5, max_message_pages: int = 100,
                expected_username: str | None = None) -> dict:
    if not 1 <= sample_size <= 10:
        raise ChatterfyExportError("A probe may read between 1 and 10 chats")
    end = end or datetime.now(timezone.utc).isoformat()
    filter_value = created_filter(start, end)
    lower, upper = map(timestamp, filter_value["value"])
    bot = next((row for row in client.discover() if row["id"] == bot_id), None)
    if bot is None:
        raise ChatterfyExportError("Source bot is not visible to this service account")
    if expected_username is not None and str(bot.get("username") or "").lstrip("@").casefold() != expected_username.lstrip("@").casefold():
        raise ChatterfyExportError("Source bot username does not match; no chat data was requested")
    access = bot.get("access") or {}
    if not isinstance(access, dict) or any(access.get(permission) != "all" for permission in
            ("chat.read", "chat.export", "message.read", "chat.contacts.read")):
        raise ChatterfyExportError("Full-scope chat/export/message/contact permissions must be verified first")
    total = client.call("/chats/v1/stats", {"bot_id": bot_id, "filter": filter_value}).get("total")
    if type(total) is not int or total < 0:
        raise ChatterfyExportError("Stats response has no valid total")
    selected = {}
    # Finish selecting chats before reading messages; do not leave an export cursor idle.
    for page in client.pages("/chats/v1/export", {"bot_id": bot_id, "limit": sample_size, "filter": filter_value}):
        for chat in page:
            cid = source_id(chat)
            if chat.get("bot_id") != bot_id:
                raise ChatterfyExportError("Export returned another bot; refusing mixed-source data")
            if not lower <= timestamp(chat.get("created_at")) <= upper:
                raise ChatterfyExportError("Server returned a chat outside the creation-date filter")
            if cid in selected and selected[cid] != chat:
                raise ChatterfyExportError("Conflicting source chat versions in the export snapshot")
            selected[cid] = chat
            if len(selected) == sample_size:
                break
        if len(selected) == sample_size:
            break
    if total and not selected:
        raise ChatterfyExportError("Stats and export disagree; no chats returned")
    if len(selected) > total or (len(selected) < sample_size and len(selected) != total):
        raise ChatterfyExportError("Stats and exported sample disagree; inspect source scope/filter")
    summaries = []
    for cid, chat in selected.items():
        ordered, pages = read_chat_history(client, chat, expected_bot_id=bot_id, max_message_pages=max_message_pages)
        filename = hashlib.sha256(cid.encode()).hexdigest() + ".json"
        write_private_json(output / filename, {"chat": chat, "messages": ordered, "pagination_complete": True})
        summaries.append({"source_chat_id": cid, "file": filename, "message_count": len(ordered), "pages": pages,
            "telegram_id_available": bool(chat.get("external_id")),
            "message_statuses": dict(Counter(str(m.get("status")) for m in ordered)),
            "sender_types": dict(Counter(str(m.get("sender_type")) for m in ordered)),
            "files": sum(len(m.get("files") or []) for m in ordered),
            "operator_messages": sum(bool(m.get("sender")) for m in ordered),
            "mailings": sum(m.get("is_mailing") is True for m in ordered),
            "replies": sum(bool(m.get("reply_message_id")) for m in ordered),
            "edited": sum(bool(m.get("edited_at")) for m in ordered),
            "oldest_message": ordered[0]["created_at"] if ordered else None,
            "latest_message": ordered[-1]["created_at"] if ordered else None})
    report = {"mode": "read_only_probe", "source_bot_id": bot_id, "target_project_label": "Ру гембл",
              "source_bot_name": bot.get("name"), "source_space_id": bot.get("space_id"), "full_scope_verified": True,
              "source_bot_username": bot.get("username"), "source_identity_verified": expected_username is not None,
              "created_filter": filter_value, "matching_chats_reported": total,
              "sample_chats": len(selected), "all_chats_exported": False, "sample_messages_fully_paginated": True,
              "media_downloaded": False, "ui_history_comparison": "pending", "crm_writes": 0,
              "requests": client.requests, "chats": summaries}
    write_private_json(output / "probe-report.json", report)
    return report
