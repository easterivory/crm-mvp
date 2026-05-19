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


class UserPasswordChange(BaseModel):
    new_password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    role_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None


class UserOut(OrmBase):
    id: uuid.UUID
    email: str
    name: str
    project_id: Optional[uuid.UUID]
    role_id: uuid.UUID
    role_name: Optional[str] = None
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
