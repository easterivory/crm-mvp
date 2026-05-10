"""
Shared string constants used across models, services and schemas.
Avoids magic strings scattered across the codebase.
"""
from enum import StrEnum


class SenderType:
    USER = "user"
    MANAGER = "manager"
    BOT = "bot"
    SYSTEM = "system"

    ALL: frozenset[str] = frozenset({USER, MANAGER, BOT, SYSTEM})


class MessageType:
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    STICKER = "sticker"
    SYSTEM = "system"

    ALL: frozenset[str] = frozenset({TEXT, IMAGE, VIDEO, AUDIO, FILE, STICKER, SYSTEM})


class LeadStatusCode:
    NEW = "new"
    IN_PROGRESS = "in_progress"
    QUALIFIED = "qualified"
    LOST = "lost"

    # Statuses from which further transitions are not allowed
    TERMINAL: frozenset[str] = frozenset({QUALIFIED, LOST})


class RoleName:
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MANAGER = "manager"

    ALL: frozenset[str] = frozenset({SUPER_ADMIN, ADMIN, MANAGER})


class AuditAction:
    LEAD_CREATED = "lead.created"
    LEAD_STATUS_CHANGED = "lead.status_changed"
    LEAD_MANAGER_ASSIGNED = "lead.manager_assigned"
    LEAD_MANAGER_REMOVED = "lead.manager_removed"
    LEAD_TAG_ADDED = "lead.tag_added"
    LEAD_TAG_REMOVED = "lead.tag_removed"


class EntityType:
    LEAD = "lead"
    CHAT = "chat"
    MESSAGE = "message"


class AlertType:
    LONG_RESPONSE = "long_response"
    MANY_UNANSWERED = "many_unanswered"


class TrackingCostModel(StrEnum):
    FIX_PDP = "fix_pdp"
    CPM = "cpm"
    CPA = "cpa"
