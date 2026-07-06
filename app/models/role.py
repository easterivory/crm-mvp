from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKey


class Role(Base, UUIDPrimaryKey):
    """
    Static reference table: super_admin / admin / manager / buyer / operator.
    Populated via seed migration — not editable through the API.
    """
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)

    users: Mapped[list[User]] = relationship("User", back_populates="role")
