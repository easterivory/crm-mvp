import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import OrmBase


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)
    role_id: uuid.UUID
    project_id: Optional[uuid.UUID] = None
    project_ids: Optional[list[uuid.UUID]] = None
    telegram_id: Optional[int] = Field(None, gt=0)
    handler_code: Optional[str] = Field(None, pattern=r"^\d{4}$")


class UserPasswordChange(BaseModel):
    new_password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    role_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None
    project_ids: Optional[list[uuid.UUID]] = None
    telegram_id: Optional[int] = Field(None, gt=0)
    handler_code: Optional[str] = Field(None, pattern=r"^\d{4}$")


class UserOut(OrmBase):
    id: uuid.UUID
    email: str
    name: str
    project_id: Optional[uuid.UUID]
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    role_id: uuid.UUID
    telegram_id: Optional[int] = None
    handler_code: Optional[str] = None
    role_name: Optional[str] = None
    is_root: bool = False
    created_at: datetime
    is_deleted: bool


class RoleOut(OrmBase):
    id: uuid.UUID
    name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginIn(BaseModel):
    email: EmailStr
    password: str
