from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.core.security import hash_password
from app.models.project import Project
from app.models.role import Role
from app.models.tracking import TrackingLink
from app.models.user import User
from app.schemas.buyer import BuyerCreate, BuyerInviteOut, BuyerUserOut
from app.services.system_setting_service import SystemSettingService

router = APIRouter(prefix="/buyers", tags=["buyers"])


@router.post("", response_model=BuyerInviteOut, status_code=status.HTTP_201_CREATED)
async def create_buyer(
    data: BuyerCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BuyerInviteOut:
    _ensure_admin(current_user)
    await _ensure_project_active(db, project_id)

    email = str(data.email).strip().lower()
    existing = await db.execute(select(User.id).where(func.lower(User.email) == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    role = await _get_manager_role(db)
    username = await _buyer_bot_username_or_error(db)

    user: User | None = None
    invite_token: UUID | None = None
    for _ in range(3):
        invite_token = uuid4()
        try:
            async with db.begin_nested():
                user = User(
                    email=email,
                    name=data.name.strip(),
                    password_hash=hash_password(data.password),
                    role_id=role.id,
                    project_id=project_id,
                    buyer_invite_token=invite_token,
                )
                user.role = role
                db.add(user)
                await db.flush()
                await db.refresh(user)
            break
        except IntegrityError:
            user = None
            invite_token = None

    if user is None or invite_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create buyer invite",
        )

    return BuyerInviteOut(
        buyer=BuyerUserOut.model_validate(user),
        invite_token=invite_token,
        invite_link=f"https://t.me/{username}?start=act_{invite_token}",
    )


@router.delete("/{buyer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_buyer(
    buyer_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_admin(current_user)
    await _ensure_project_active(db, project_id)
    if buyer_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own user",
        )

    result = await db.execute(
        select(User).where(
            User.id == buyer_id,
            User.project_id == project_id,
            User.is_deleted.is_(False),
        )
    )
    buyer = result.scalar_one_or_none()
    if buyer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Buyer not found",
        )

    links_count = await _count_buyer_links(db, buyer_id)
    if (
        buyer.buyer_telegram_id is None
        and buyer.buyer_invite_token is None
        and links_count == 0
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Buyer not found",
        )

    await db.execute(
        update(User)
        .where(User.id == buyer_id, User.is_deleted.is_(False))
        .values(
            is_deleted=True,
            buyer_telegram_id=None,
            buyer_invite_token=None,
        )
    )


def _ensure_admin(user: User) -> None:
    if user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin/super_admin can manage buyers",
        )


async def _ensure_project_active(db: AsyncSession, project_id: UUID) -> None:
    result = await db.execute(
        select(Project.id).where(
            Project.id == project_id,
            Project.is_deleted.is_(False),
            Project.status == "active",
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project does not exist or is archived",
        )


async def _get_manager_role(db: AsyncSession) -> Role:
    result = await db.execute(select(Role).where(Role.name == RoleName.MANAGER))
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Manager role is not configured",
        )
    return role


async def _buyer_bot_username_or_error(db: AsyncSession) -> str:
    username = (await SystemSettingService(db).get_effective_buyer_bot_config()).username
    if not username:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="buyer_bot_username is not configured",
        )
    return username


async def _count_buyer_links(db: AsyncSession, buyer_id: UUID) -> int:
    result = await db.execute(
        select(func.count(TrackingLink.id)).where(TrackingLink.buyer_id == buyer_id)
    )
    return int(result.scalar_one() or 0)
