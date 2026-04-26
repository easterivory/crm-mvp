from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.user import LoginIn, TokenOut, UserCreate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    raise NotImplementedError


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.get("", response_model=PaginatedResponse[UserOut])
async def list_users(
    limit: int = 50,
    offset: int = 0,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserOut]:
    raise NotImplementedError


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)) -> UserOut:
    raise NotImplementedError
