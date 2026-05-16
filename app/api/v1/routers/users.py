from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.user import LoginIn, RoleOut, TokenOut, UserCreate, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    return await UserService(db).login(data)


@router.get("/me", response_model=UserOut)
async def me(current_user: Any = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    _current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoleOut]:
    return await UserService(db).list_roles()


@router.get("", response_model=PaginatedResponse[UserOut])
async def list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: Optional[UUID] = Query(default=None),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserOut]:
    items, total = await UserService(db).list_users(
        project_id=project_id,
        limit=limit,
        offset=offset,
        actor=current_user,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    return await UserService(db).create_user(data, actor=current_user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await UserService(db).delete_user(
        user_id=user_id,
        actor=current_user,
    )
