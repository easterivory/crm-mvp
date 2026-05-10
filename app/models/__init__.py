"""
Import all models here so SQLAlchemy's mapper registry is populated
before Alembic autogenerate or any ORM query runs.
Order matters for forward-reference resolution.
"""

from app.models.base import Base  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.role import Role  # noqa: F401
from app.models.lead_status import LeadStatus  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.chat import Chat  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.lead import Lead, LeadTag  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.alert import Alert  # noqa: F401
from app.models.daily_stats import DailyStats  # noqa: F401
from app.models.bot import Bot, BotVersion, BotStep, ChatBotState  # noqa: F401
from app.models.tracking import TrackingEvent, TrackingLink  # noqa: F401

__all__ = [
    "Base",
    "Project",
    "Role",
    "LeadStatus",
    "User",
    "Chat",
    "Message",
    "Tag",
    "Lead",
    "LeadTag",
    "AuditLog",
    "Alert",
    "DailyStats",
    "Bot",
    "BotVersion",
    "BotStep",
    "ChatBotState",
    "TrackingLink",
    "TrackingEvent",
]
