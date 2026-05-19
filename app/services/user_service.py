"""
UserService - authentication and user management.

The service owns business validation and security-sensitive operations:
password verification, password hashing, token creation and project/role
consistency checks. Routers stay thin and repositories stay query-focused.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.user import User
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    LoginIn,
    RoleOut,
    TokenOut,
    UserCreate,
    UserOut,
    UserPasswordChange,
    UserUpdate,
)


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)
        self.project_repo = ProjectRepository(db)

    async def login(self, data: LoginIn) -> TokenOut:
        email = self._normalize_email(str(data.email))
        user = await self.user_repo.get_by_email(email)

        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return TokenOut(access_token=create_access_token(subject=user.id))

    async def list_users(
        self,
        limit: int,
        offset: int,
        actor: User,
        project_id: UUID | None = None,
    ) -> tuple[list[UserOut], int]:
        scoped_project_id = self._resolve_staff_project_scope(actor, project_id)
        users = await self.user_repo.list_active(
            project_id=scoped_project_id,
            limit=limit,
            offset=offset,
        )
        total = await self.user_repo.count_active(project_id=scoped_project_id)
        return [UserOut.model_validate(user) for user in users], total

    async def list_roles(self) -> list[RoleOut]:
        roles = await self.user_repo.list_roles()
        return [RoleOut.model_validate(role) for role in roles]

    async def create_user(self, data: UserCreate, actor: User) -> UserOut:
        self._ensure_can_create_user(actor)
        email = self._normalize_email(str(data.email))

        existing = await self.user_repo.get_any_by_email(email)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists",
            )

        role = await self.user_repo.get_role_by_id(data.role_id)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Role does not exist",
            )

        if role.name not in RoleName.ALL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Role is not supported for staff users",
            )

        if actor.role_name == RoleName.ADMIN and role.name not in RoleName.ADMIN_MANAGED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin can create only manager/operator users",
            )

        if role.name == RoleName.SUPER_ADMIN and actor.role_name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can create super_admin users",
            )

        if role.name != RoleName.SUPER_ADMIN and data.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="project_id is required for non-super_admin users",
            )

        if data.project_id is not None:
            self._ensure_actor_can_manage_project(actor, data.project_id)

        project_id = None if role.name == RoleName.SUPER_ADMIN else data.project_id

        if project_id is not None:
            project = await self.project_repo.get_active(project_id)
            if project is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Project does not exist",
                )

        try:
            async with self.db.begin_nested():
                user = await self.user_repo.create(
                    email=email,
                    name=data.name,
                    password_hash=hash_password(data.password),
                    role_id=data.role_id,
                    project_id=project_id,
                )
                user.role = role
        except IntegrityError:
            existing = await self.user_repo.get_any_by_email(email)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this email already exists",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not create user",
            )

        return UserOut.model_validate(user)

    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        actor: User,
    ) -> UserOut:
        target = await self.user_repo.get_by_id(user_id)
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        self._ensure_can_manage_target(actor, target)
        values = data.model_dump(exclude_unset=True)

        if "name" in values and values["name"] is not None:
            values["name"] = values["name"].strip()
            if not values["name"]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Name must not be empty",
                )

        if "role_id" in values and values["role_id"] is not None:
            role = await self.user_repo.get_role_by_id(values["role_id"])
            if role is None or role.name not in RoleName.ALL:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Role does not exist",
                )
            if actor.role_name == RoleName.ADMIN and role.name not in RoleName.ADMIN_MANAGED:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin can assign only manager/operator roles",
                )

        next_role_id = values.get("role_id", target.role_id)
        next_role = await self.user_repo.get_role_by_id(next_role_id)
        if next_role is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Role does not exist",
            )

        if next_role.name == RoleName.SUPER_ADMIN:
            values["project_id"] = None
        elif "project_id" in values:
            if values["project_id"] is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="project_id is required for non-super_admin users",
                )
            self._ensure_actor_can_manage_project(actor, values["project_id"])
        elif target.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="project_id is required for non-super_admin users",
            )

        updated = await self.user_repo.update_user(user_id, **values)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return UserOut.model_validate(updated)

    async def change_password(
        self,
        user_id: UUID,
        data: UserPasswordChange,
        actor: User,
    ) -> None:
        target = await self.user_repo.get_by_id(user_id)
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        self._ensure_can_manage_target(actor, target)
        updated = await self.user_repo.update_password_hash(
            user_id,
            hash_password(data.new_password),
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

    async def delete_user(
        self,
        user_id: UUID,
        actor: User,
    ) -> None:
        if user_id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own user",
            )

        target = await self.user_repo.get_by_id(user_id)
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        self._ensure_can_manage_target(actor, target)

        deleted = await self.user_repo.soft_delete_by_id(user_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _ensure_can_create_user(actor: User) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin/admin can create staff users",
            )

    @staticmethod
    def _resolve_staff_project_scope(
        actor: User,
        project_id: UUID | None,
    ) -> UUID | None:
        if actor.role_name == RoleName.SUPER_ADMIN:
            return project_id

        if actor.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with a project",
            )

        if project_id is not None and project_id != actor.project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project is not accessible for current user",
            )

        return actor.project_id

    @classmethod
    def _ensure_actor_can_manage_project(cls, actor: User, project_id: UUID) -> None:
        if actor.role_name == RoleName.SUPER_ADMIN:
            return
        if actor.role_name == RoleName.ADMIN and actor.project_id == project_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project is not manageable for current user",
        )

    @classmethod
    def _ensure_can_manage_target(cls, actor: User, target: User) -> None:
        target_role = target.role_name
        if actor.role_name == RoleName.SUPER_ADMIN:
            return

        if target_role == RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="super_admin users cannot be managed here",
            )

        if actor.role_name == RoleName.ADMIN:
            if target.project_id != actor.project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Target user is outside current admin project",
                )
            if target_role not in RoleName.ADMIN_MANAGED:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin can manage only manager/operator users",
                )
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin/admin can manage staff users",
        )
