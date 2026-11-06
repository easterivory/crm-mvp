"""Offline history adapter and explicit tokenless staging import. Never sends messages."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid5

from app.services.chatterfy_export_service import ChatterfyExportError, DEFAULT_START, source_id, timestamp

NAMESPACE = UUID("6191594a-dfb3-4b9e-a998-683a2a2f9059")
PROVENANCE = "__chatterfy_import"
START = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?(?:\s+([A-Za-z0-9_-]{1,64}))?\s*$", re.I)
SOURCE_STATUSES = {"ai", "manual", "waiting", "ignore", "blocked", "error", "stopped", "finished"}


def manual_import_fields(fields) -> bool:
    value = fields.get(PROVENANCE) if isinstance(fields, dict) else None
    return isinstance(value, dict) and value.get("schema") == 1 and value.get("mode") == "manual"


async def is_manual_history_chat(db, chat) -> bool:
    if not getattr(chat, "is_imported", False):
        return False
    from sqlalchemy import select
    from app.models.lead import Lead
    fields = await db.scalar(select(Lead.custom_fields).where(Lead.chat_id == chat.id))
    return manual_import_fields(fields)


def stable_id(bot_id: UUID, kind: str, original: str) -> UUID:
    return uuid5(NAMESPACE, f"{bot_id}:{kind}:{original}")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_key(campaign_id: str | None, source: str | None) -> str:
    # JSON avoids collisions between absent IDs, separators and real source strings.
    return json.dumps([campaign_id, source], separators=(",", ":"))


def source_requires_mapping(provenance: dict) -> bool:
    return bool(provenance.get("source_id")) and provenance.get("provider_type") != "organic"


@dataclass(frozen=True)
class PreparedChat:
    source_chat_id: str
    telegram_id: str
    chat: dict
    provenance: dict
    messages: tuple[dict, ...]
    warnings: tuple[str, ...]


def prepare_chat(envelope: dict, *, source_bot_id: str, source_username: str,
                 created_from: str = DEFAULT_START) -> PreparedChat:
    if envelope.get("pagination_complete") is not True:
        raise ChatterfyExportError("Incomplete history cannot be imported")
    chat, history = envelope.get("chat"), envelope.get("messages")
    if not isinstance(chat, dict) or not isinstance(history, list):
        raise ChatterfyExportError("Expected a chat with a complete message list")
    if chat.get("bot_id") != source_bot_id:
        raise ChatterfyExportError("Archive contains a different source bot")
    cid, created = source_id(chat), timestamp(chat.get("created_at"))
    if created < timestamp(created_from):
        raise ChatterfyExportError("Chat was created before the agreed cohort boundary")
    telegram_id = str(chat.get("external_id") or "")
    if not re.fullmatch(r"[1-9][0-9]{0,18}", telegram_id) or int(telegram_id) > 2**63 - 1:
        raise ChatterfyExportError("A verified positive numeric Telegram identity is required")
    if chat.get("status") not in SOURCE_STATUSES:
        raise ChatterfyExportError("Unknown source chat status")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", source_username.lstrip("@")):
        raise ChatterfyExportError("Invalid source bot username")
    tags = chat.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ChatterfyExportError("Unknown source tag schema")
    lead = chat.get("lead") or {}
    if not isinstance(lead, dict) or not isinstance(lead.get("params", {}), dict):
        raise ChatterfyExportError("Unknown source attribution schema")
    for key in ("campaign_id", "source_id"):
        if lead.get(key) is not None and not isinstance(lead[key], str):
            raise ChatterfyExportError("Unknown source identifier schema")
    seen, ordered = {}, []
    for message in history:
        if not isinstance(message, dict):
            raise ChatterfyExportError("Invalid source message")
        mid = source_id(message)
        if mid in seen:
            raise ChatterfyExportError("Duplicate message IDs in a chat archive")
        seen[mid] = message
        if message.get("chat_id") != cid or message.get("type") != "message":
            raise ChatterfyExportError("Foreign chat message in archive")
        if message.get("sender_type") not in {"incoming", "outcoming"}:
            raise ChatterfyExportError("Unknown message author")
        if message.get("status") not in {"ready", "removed", "failed", "waiting", "schedule"}:
            raise ChatterfyExportError("Unknown message delivery status")
        if not isinstance(message.get("content"), str):
            raise ChatterfyExportError("Unknown message text format")
        files = message.get("files") or []
        if not isinstance(files, list) or any(not isinstance(file, dict) for file in files):
            raise ChatterfyExportError("Unknown attachment schema")
        if message.get("reply_message_id") is not None and not isinstance(message["reply_message_id"], str):
            raise ChatterfyExportError("Invalid reply reference")
        timestamp(message.get("created_at"))
        for key in ("edited_at", "published_at"):
            if message.get(key):
                timestamp(message[key])
        ordered.append(message)
    ordered.sort(key=lambda m: (timestamp(m["created_at"]), m["id"]))
    delivered = [m for m in ordered if m["status"] in {"ready", "removed"}]
    starts = []
    for message in delivered:
        match = START.fullmatch(message["content"]) if message["sender_type"] == "incoming" else None
        if match and match.group(1) and match.group(1) not in starts:
            starts.append(match.group(1))
    metadata = {
        "schema": 1, "source_bot_id": source_bot_id, "source_username": source_username.lstrip("@"),
        "source_chat_id": cid, "source_created_at": chat["created_at"], "archive_digest": digest(envelope),
        "source_status": chat["status"], "current_step_id": chat.get("current_step_id"),
        "campaign_id": lead.get("campaign_id"), "source_id": lead.get("source_id"),
        "source_key": source_key(lead.get("campaign_id"), lead.get("source_id")),
        "provider_type": lead.get("provider_type"), "params": lead.get("params", {}),
        "tracker_events": lead.get("events", []), "source_tag_ids": sorted(set(tags)),
        "source_custom_fields": chat.get("custom_fields"), "start_payloads": starts,
        "excluded_delivery_ids": [m["id"] for m in ordered if m["status"] not in {"ready", "removed"}],
        "mode": "manual", "resume_approved": False,
    }
    warnings = []
    if any(m.get("files") for m in delivered):
        warnings.append("media_download_required")
    if any(m.get("reply_message_id") not in seen for m in delivered if m.get("reply_message_id")):
        warnings.append("reply_target_missing")
    if lead.get("source_id") and f't_{lead["source_id"]}' not in starts:
        warnings.append("source_and_start_payload_differ")
    if metadata["excluded_delivery_ids"]:
        warnings.append("unsent_messages_archived_not_delivered")
    return PreparedChat(cid, telegram_id, chat, metadata, tuple(delivered), tuple(warnings))


def archive_report(chats: list[PreparedChat]) -> dict:
    sources, steps, identities = {}, {}, set()
    for item in chats:
        if item.telegram_id in identities:
            raise ChatterfyExportError("Two source chats share a Telegram identity; resolve before import")
        identities.add(item.telegram_id)
        key = item.provenance["source_key"]
        row = sources.setdefault(key, {"campaign_id": item.provenance["campaign_id"],
            "source_id": item.provenance["source_id"], "provider_type": item.provenance["provider_type"],
            "chats": 0, "observed_start_payloads": set()})
        if row["provider_type"] != item.provenance["provider_type"]:
            raise ChatterfyExportError("Conflicting source types; resolve attribution before creating links")
        row["chats"] += 1
        row["observed_start_payloads"].update(item.provenance["start_payloads"])
        step = item.provenance["current_step_id"]
        steps[step] = steps.get(step, 0) + 1
    return {"mode": "offline_preparation", "chats": len(chats),
        "delivered_history_records": sum(len(c.messages) for c in chats),
        "sources": [{**row, "key": key, "observed_start_payloads": sorted(row["observed_start_payloads"])}
                    for key, row in sorted(sources.items())],
        "steps": [{"source_step_id": step, "chats": count, "destination_step_id": None}
                  for step, count in sorted(steps.items(), key=lambda pair: str(pair[0]))],
        "source_tag_ids": sorted({tag for c in chats for tag in c.provenance["source_tag_ids"]}),
        "warnings": sorted({warning for c in chats for warning in c.warnings}),
        "crm_writes": 0, "telegram_sends": 0, "funnel_resume": "manual_only",
        "historical_clicks_imported": False, "complete_cohort": False}


class ChatterfyStagingImporter:
    """Per-chat atomic inserts. Caller commits; refuses live bots and all existing chat conflicts."""

    def __init__(self, db, *, project_id: UUID, bot_id: UUID, source_bot_id: str,
                 source_username: str, status_id: UUID, tag_map: dict[str, UUID],
                 source_map: dict[str, UUID]):
        self.db, self.project_id, self.bot_id = db, project_id, bot_id
        self.source_bot_id, self.source_username = source_bot_id, source_username.lstrip("@")
        self.status_id, self.tag_map, self.source_map = status_id, tag_map, source_map

    async def import_chat(self, item: PreparedChat, *, dry_run: bool = True) -> dict:
        from sqlalchemy import select
        from app.models import Bot, Chat, Lead, LeadTag, LeadStatus, Message, Project, Tag, TrackingLink
        from app.models.advertising import AdvertisingConfig

        # Lock the destination before checking its configuration. A token update must not
        # race the import. No source calls, media downloads or Telegram calls under this lock.
        statement = select(Bot).where(Bot.id == self.bot_id).execution_options(populate_existing=True)
        bot = await self.db.scalar(statement if dry_run else statement.with_for_update())
        project = await self.db.get(Project, self.project_id)
        if (not bot or bot.is_deleted or bot.project_id != self.project_id or not project or project.is_deleted or project.status != "active"
                or bot.transport_type != "bot_api" or bot.telegram_token or bot.telegram_bot_id
                or bot.active_funnel_id or bot.active_funnel_version_id):
            raise ChatterfyExportError("Destination must be an active tokenless bot draft without an active funnel")
        if bot.bot_username and bot.bot_username.casefold() != self.source_username.casefold():
            raise ChatterfyExportError("Destination username differs from the source")
        if (item.provenance["source_bot_id"] != self.source_bot_id
                or item.provenance["source_username"].casefold() != self.source_username.casefold()):
            raise ChatterfyExportError("Prepared chat does not match the confirmed source")
        ad = await self.db.scalar(select(AdvertisingConfig.id).where(AdvertisingConfig.project_id == self.project_id,
            AdvertisingConfig.enabled.is_(True), AdvertisingConfig.settings_json["bot_ids"].contains([str(self.bot_id)])))
        if ad:
            raise ChatterfyExportError("Remove the staging bot from active advertising scenarios first")
        if not await self.db.get(LeadStatus, self.status_id):
            raise ChatterfyExportError("Explicit destination lead status is required")
        for tag in item.provenance["source_tag_ids"]:
            mapped = await self.db.get(Tag, self.tag_map.get(tag)) if self.tag_map.get(tag) else None
            if mapped is None or mapped.project_id != self.project_id:
                raise ChatterfyExportError("Every source tag must be mapped to a tag in the destination project")
        source = item.provenance["source_key"]
        link_id = self.source_map.get(source)
        if source_requires_mapping(item.provenance) and link_id is None:
            raise ChatterfyExportError("Source attribution must be explicitly mapped; do not silently drop it")
        link = await self.db.get(TrackingLink, link_id) if link_id else None
        if link_id and (not link or link.project_id != self.project_id or link.bot_id != self.bot_id
                        or link.destination_type != "bot"):
            raise ChatterfyExportError("Tracking link belongs to a different destination")
        chat_id = stable_id(self.bot_id, "chat", item.source_chat_id)
        existing = await self.db.scalar(select(Chat).where(Chat.project_id == self.project_id,
            Chat.bot_id == self.bot_id, Chat.external_chat_id == item.telegram_id))
        if existing:
            lead = await self.db.scalar(select(Lead).where(Lead.chat_id == existing.id))
            prior = (lead.custom_fields or {}).get(PROVENANCE, {}) if lead else {}
            if (not existing.is_deleted and existing.id == chat_id and prior.get("archive_digest") == item.provenance["archive_digest"]):
                return {"status": "already_imported", "chat_id": str(chat_id), "messages": 0}
            raise ChatterfyExportError("Existing chat or changed archive conflicts with staging import; no overwrite")
        # Media must first be downloaded and verified. Never leave a broken attachment
        # masquerading as a successfully imported conversation.
        if any(m.get("files") for m in item.messages):
            raise ChatterfyExportError("Media chats are preparation-only until attachment migration is verified")
        user_messages = [m for m in item.messages if m["sender_type"] == "incoming" and m["status"] == "ready"]
        outgoing = [m for m in item.messages if m["sender_type"] == "outcoming" and m["status"] == "ready"]
        operators = [m for m in outgoing if m.get("sender")]
        latest = lambda rows: max((timestamp(m.get("published_at") or m["created_at"]) for m in rows), default=None)
        read_state = item.chat.get("read_state") or {}
        unread = read_state.get("incoming_unread_count", 0)
        if type(unread) is not int or unread < 0:
            raise ChatterfyExportError("Invalid source read state")
        last_at = latest(user_messages + outgoing)
        name, username = item.chat.get("name"), item.chat.get("username")
        if any(value is not None and (not isinstance(value, str) or len(value) > 255) for value in (name, username)):
            raise ChatterfyExportError("Invalid source contact fields")
        if dry_run:
            return {"status": "ready", "chat_id": str(chat_id), "messages": len(item.messages)}
        imported_at = datetime.now(timezone.utc)
        chat = Chat(id=chat_id, project_id=self.project_id, bot_id=self.bot_id,
            external_chat_id=item.telegram_id, external_user_id=item.telegram_id,
            contact_name=name, created_at=timestamp(item.chat["created_at"]), updated_at=imported_at,
            is_imported=True, imported_at=imported_at, import_identity_pending=False,
            tracking_link_id=link_id, last_message_at=last_at, last_user_message_at=latest(user_messages),
            last_client_message_at=latest(user_messages), last_manager_reply_at=latest(operators),
            last_operator_message_at=latest(operators), is_read=unread == 0,
            last_read_at=last_at if unread == 0 else None, is_blocked=item.chat["status"] == "blocked")
        self.db.add(chat)
        await self.db.flush()
        lead = Lead(id=stable_id(self.bot_id, "lead", item.source_chat_id), project_id=self.project_id,
            chat_id=chat_id, status_id=self.status_id, name=name, username=username,
            created_at=chat.created_at, custom_fields={PROVENANCE: item.provenance})
        self.db.add(lead)
        await self.db.flush()
        for tag_id in sorted({self.tag_map[tag] for tag in item.provenance["source_tag_ids"]}):
            self.db.add(LeadTag(lead_id=lead.id, tag_id=tag_id, created_at=imported_at))
        imported_ids = {m["id"] for m in item.messages}
        for message in item.messages:
            source_time = timestamp(message.get("published_at") or message["created_at"])
            incoming = message["sender_type"] == "incoming"
            self.db.add(Message(id=stable_id(self.bot_id, "message", message["id"]), chat_id=chat_id,
                external_message_id=None, message_type="text",
                sender_type="user" if incoming else "manager" if message.get("sender") else "bot",
                body=message["content"], created_at=source_time, funnel_processed_at=imported_at,
                deleted_at=imported_at if message["status"] == "removed" else None,
                edited_at=timestamp(message["edited_at"]) if message.get("edited_at") else None,
                raw_payload_json={"chatterfy_import": message, "historical_import": True},
                # Only exact source-confirmed payloads receive message-level attribution.
                tracking_link_id=link_id if incoming and message["content"].strip() == f'/start t_{item.provenance["source_id"]}' else None))
        await self.db.flush()
        # Replies can reference messages later in the source result. Resolve after all inserts.
        for message in item.messages:
            target = message.get("reply_message_id")
            if target in imported_ids:
                row = await self.db.get(Message, stable_id(self.bot_id, "message", message["id"]))
                row.reply_to_message_id = stable_id(self.bot_id, "message", target)
        await self.db.flush()
        return {"status": "imported", "chat_id": str(chat_id), "messages": len(item.messages)}


async def create_staging_links(db, *, project_id: UUID, bot_id: UUID, proposals: list[dict]) -> dict[str, str]:
    """Explicitly approved source->link mapping, never guess a source from later starts."""
    from sqlalchemy import or_, select
    from app.models import Bot, TrackingLink

    bot = await db.scalar(select(Bot).where(Bot.id == bot_id).with_for_update()
                          .execution_options(populate_existing=True))
    if (not bot or bot.project_id != project_id or bot.is_deleted or bot.transport_type != "bot_api" or bot.telegram_token
            or bot.telegram_bot_id or bot.active_funnel_id or bot.active_funnel_version_id):
        raise ChatterfyExportError("Tracking links can only be prepared for a tokenless staging bot")
    result, codes = {}, set()
    for proposal in proposals:
        key, code, name = proposal.get("source_key"), proposal.get("code"), proposal.get("name")
        if (not isinstance(key, str) or not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code)
                or not isinstance(name, str) or not 1 <= len(name.strip()) <= 255 or key in result or code in codes):
            raise ChatterfyExportError("Invalid or duplicate source/link proposal")
        try:
            parts = json.loads(key)
        except ValueError:
            raise ChatterfyExportError("Source link key must contain the exact campaign/source pair") from None
        if (not isinstance(parts, list) or len(parts) != 2 or not isinstance(parts[1], str) or not parts[1]
                or (parts[0] is not None and not isinstance(parts[0], str))):
            raise ChatterfyExportError("Source link key must contain the exact campaign/source pair")
        codes.add(code)
        link_id = stable_id(bot_id, "tracking", key)
        matches = list((await db.scalars(select(TrackingLink).where(or_(TrackingLink.ref_code == code,
            TrackingLink.code == code, TrackingLink.id == link_id)))).all())
        if len(matches) > 1:
            raise ChatterfyExportError("Multiple conflicting tracking links; no automatic reconciliation")
        existing = matches[0] if matches else None
        if existing:
            if (existing.id != link_id or existing.project_id != project_id or existing.bot_id != bot_id
                    or existing.code != code or existing.ref_code != code):
                raise ChatterfyExportError("Tracking code collision; choose a new code, do not overwrite existing links")
        else:
            db.add(TrackingLink(id=link_id, project_id=project_id, bot_id=bot_id, name=name, title=name,
                ref_code=code, code=code, destination_type="bot", is_active=False))
            await db.flush()
        result[key] = str(link_id)
    return result
