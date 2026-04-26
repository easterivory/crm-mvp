import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class TagCreate(BaseModel):
    name: str = Field(..., max_length=100)


class TagOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    created_at: datetime
