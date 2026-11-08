"""Opt-in cloud connections and immutable, human-approved configuration plans."""
from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class AssistantConnection(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "assistant_connections"
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(255))
    resource: Mapped[str] = mapped_column(Text)
    issuer: Mapped[str] = mapped_column(Text)
    project_ids: Mapped[list] = mapped_column(JSONB)
    scopes: Mapped[list] = mapped_column(JSONB)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantCode(Base, TimestampMixin):
    __tablename__ = "assistant_oauth_codes"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assistant_connections.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantToken(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "assistant_oauth_tokens"
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assistant_connections.id"), index=True)
    access_digest: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_digest: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    refresh_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantProposal(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "assistant_change_proposals"
    __table_args__ = (
        Index("uq_assistant_proposal_request", "connection_id", "request_id", unique=True),
        Index("ix_assistant_proposals_project_status", "project_id", "status", "created_at"),
        CheckConstraint("status IN ('draft','pending_approval','applied','rejected','cancelled','expired','stale','failed')", name="ck_assistant_proposal_status"),
    )
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assistant_connections.id"))
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    request_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    handler_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval")
    plan_json: Mapped[dict] = mapped_column(JSONB)
    snapshot_json: Mapped[dict] = mapped_column(JSONB)
    plan_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    approved_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))


class AssistantSecureInput(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "assistant_secure_inputs"
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    kind: Mapped[str] = mapped_column(String(30), default="source_url")
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bound_proposal_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assistant_change_proposals.id"))
