"""
Import all models here so SQLAlchemy's mapper registry is populated
before Alembic autogenerate or any ORM query runs.
Order matters for forward-reference resolution.
"""

from app.models.base import Base  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.google_sheets import ProjectGoogleSheetsConfig  # noqa: F401
from app.models.lander import ProjectDomain, ProjectLander  # noqa: F401
from app.models.role import Role  # noqa: F401
from app.models.lead_status import LeadStatus  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.chat import Chat  # noqa: F401
from app.models.chat_event_log import ChatEventLog  # noqa: F401
from app.models.chat_filter_preset import ChatFilterPreset  # noqa: F401
from app.models.broadcast import Broadcast, BroadcastRecipient, BroadcastTemplate, BroadcastUpload  # noqa: F401
from app.models.message import Message, MessageUpload  # noqa: F401
from app.models.project_snippet import ProjectSnippet  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.lead import Lead, LeadTag  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.alert import Alert  # noqa: F401
from app.models.daily_stats import DailyStats  # noqa: F401
from app.models.bot import Bot, BotConfigAuditLog, BotVersion, BotStep, ChatBotState  # noqa: F401
from app.models.tracking import TrackingEvent, TrackingLink, TrackingSpend  # noqa: F401
from app.models.funnel import (  # noqa: F401
    ChatFunnelState,
    Funnel,
    FunnelEdge,
    FunnelFieldMapping,
    FunnelPushRule,
    FunnelRuntimeLog,
    FunnelScheduledJob,
    FunnelStepLog,
    FunnelStep,
    FunnelVersion,
)
from app.models.partner import PartnerIntegration, LeadSubmission  # noqa: F401

__all__ = [
    "Base",
    "Project",
    "ProjectGoogleSheetsConfig",
    "ProjectDomain",
    "ProjectLander",
    "Role",
    "LeadStatus",
    "User",
    "Chat",
    "ChatEventLog",
    "ChatFilterPreset",
    "Broadcast",
    "BroadcastRecipient",
    "BroadcastTemplate",
    "BroadcastUpload",
    "Message",
    "MessageUpload",
    "ProjectSnippet",
    "Tag",
    "Lead",
    "LeadTag",
    "AuditLog",
    "Alert",
    "DailyStats",
    "Bot",
    "BotConfigAuditLog",
    "BotVersion",
    "BotStep",
    "ChatBotState",
    "TrackingLink",
    "TrackingSpend",
    "TrackingEvent",
    "Funnel",
    "FunnelVersion",
    "FunnelStep",
    "FunnelEdge",
    "FunnelPushRule",
    "FunnelRuntimeLog",
    "FunnelScheduledJob",
    "FunnelStepLog",
    "FunnelFieldMapping",
    "ChatFunnelState",
    "PartnerIntegration",
    "LeadSubmission",
]
