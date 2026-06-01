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
    PHOTO = "photo"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    DOCUMENT = "document"
    AUDIO = "audio"
    ANIMATION = "animation"
    FILE = "file"
    STICKER = "sticker"
    SYSTEM = "system"
    UNKNOWN = "unknown"

    ALL: frozenset[str] = frozenset(
        {
            TEXT,
            PHOTO,
            IMAGE,
            VIDEO,
            VOICE,
            VIDEO_NOTE,
            DOCUMENT,
            AUDIO,
            ANIMATION,
            FILE,
            STICKER,
            SYSTEM,
            UNKNOWN,
        }
    )


class ChatEventType:
    STATUS_CHANGE = "status_change"
    TAG_ADDED = "tag_added"
    MANAGER_ASSIGNED = "manager_assigned"
    SLA_BREACHED = "SLA_breached"
    NOTE_ADDED = "note_added"

    ALL: frozenset[str] = frozenset(
        {
            STATUS_CHANGE,
            TAG_ADDED,
            MANAGER_ASSIGNED,
            SLA_BREACHED,
            NOTE_ADDED,
        }
    )


class LeadStatusCode:
    NEW = "new"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    APPLIED = "applied"
    QUALIFIED = "qualified"
    LOST = "lost"

    # Statuses from which further transitions are not allowed
    TERMINAL: frozenset[str] = frozenset({QUALIFIED, LOST})
    SUBMITTED_SET: frozenset[str] = frozenset({SUBMITTED, APPLIED, QUALIFIED})


class RoleName:
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"

    ALL: frozenset[str] = frozenset({SUPER_ADMIN, ADMIN, MANAGER, OPERATOR})
    STAFF: frozenset[str] = frozenset({ADMIN, MANAGER, OPERATOR})
    ADMIN_MANAGED: frozenset[str] = frozenset({MANAGER, OPERATOR})


class AuditAction:
    LEAD_CREATED = "lead.created"
    LEAD_STATUS_CHANGED = "lead.status_changed"
    LEAD_MANAGER_ASSIGNED = "lead.manager_assigned"
    LEAD_MANAGER_REMOVED = "lead.manager_removed"
    LEAD_TAG_ADDED = "lead.tag_added"
    LEAD_TAG_REMOVED = "lead.tag_removed"
    CHAT_RESET = "chat.reset"
    PROJECT_ARCHIVED = "project.archived"
    PROJECT_RESTORED = "project.restored"
    LEAD_SUBMITTED = "lead.submitted"
    LEAD_REJECTED = "lead.rejected"


class EntityType:
    LEAD = "lead"
    CHAT = "chat"
    MESSAGE = "message"
    PROJECT = "project"


class AlertType:
    LONG_RESPONSE = "long_response"
    MANY_UNANSWERED = "many_unanswered"


class TrackingCostModel(StrEnum):
    FIX_PDP = "fix_pdp"
    CPM = "cpm"
    CPA = "cpa"


class TrackingSpendSource(StrEnum):
    CRM_MANUAL = "crm_manual"
    BUYER_BOT = "buyer_bot"
