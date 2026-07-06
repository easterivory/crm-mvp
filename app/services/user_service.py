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
from app.services.access_control import (
    accessible_project_ids,
    has_project_access,
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
        include_super_admins = (
            actor.role_name == RoleName.SUPER_ADMIN and scoped_project_id is not None
        )
        users = await self.user_repo.list_active(
            project_id=scoped_project_id,
            limit=limit,
            offset=offset,
            include_super_admins=include_super_admins,
        )
        total = await self.user_repo.count_active(
            project_id=scoped_project_id,
            include_super_admins=include_super_admins,
        )
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
        if data.telegram_id is not None:
            existing_by_telegram = await self.user_repo.get_by_telegram_id(data.telegram_id)
            if existing_by_telegram is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this Telegram ID already exists",
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
                detail="Admin can create only manager/buyer/operator users",
            )

        if role.name == RoleName.SUPER_ADMIN and actor.role_name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can create super_admin users",
            )

        project_ids = self._normalize_project_ids(data.project_ids, data.project_id)
        if role.name != RoleName.SUPER_ADMIN and not project_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least one project access is required for non-super_admin users",
            )

        for project_id in project_ids:
            self._ensure_actor_can_manage_project(actor, project_id)

        if role.name == RoleName.SUPER_ADMIN:
            project_ids = []

        project_id = None if role.name == RoleName.SUPER_ADMIN else project_ids[0]

        await self._ensure_projects_active(project_ids)
        if data.handler_code:
            existing_by_handler_code = await self.user_repo.get_by_handler_code(
                handler_code=data.handler_code,
            )
            if existing_by_handler_code is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Handler code is already used in this project",
                )

        try:
            async with self.db.begin_nested():
                user = await self.user_repo.create(
                    email=email,
                    name=data.name,
                    password_hash=hash_password(data.password),
                    role_id=data.role_id,
                    project_id=project_id,
                    telegram_id=data.telegram_id,
                    handler_code=data.handler_code,
                )
                user.role = role
                if project_ids:
                    await self.user_repo.replace_project_accesses(user.id, project_ids)
                    user = await self.user_repo.get_by_id(user.id) or user
        except IntegrityError:
            existing = await self.user_repo.get_any_by_email(email)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this email already exists",
                )
            if data.telegram_id is not None:
                existing_by_telegram = await self.user_repo.get_by_telegram_id(data.telegram_id)
                if existing_by_telegram is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="User with this Telegram ID already exists",
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
        provided_project_ids = values.pop("project_ids", None)

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
                    detail="Admin can assign only manager/buyer/operator roles",
                )

        if "telegram_id" in values and values["telegram_id"] is not None:
            existing_by_telegram = await self.user_repo.get_by_telegram_id(values["telegram_id"])
            if existing_by_telegram is not None and existing_by_telegram.id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this Telegram ID already exists",
                )

        next_role_id = values.get("role_id", target.role_id)
        next_role = await self.user_repo.get_role_by_id(next_role_id)
        if next_role is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Role does not exist",
            )

        if target.is_root and next_role.name != RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Root role cannot be downgraded",
            )

        if next_role.name == RoleName.SUPER_ADMIN:
            values["project_id"] = None
            next_project_ids: list[UUID] = []
            if "handler_code" in values:
                values["handler_code"] = None
        else:
            if provided_project_ids is not None:
                next_project_ids = self._normalize_project_ids(
                    provided_project_ids,
                    values.get("project_id"),
                )
            elif "project_id" in values:
                next_project_ids = self._normalize_project_ids(None, values["project_id"])
            else:
                next_project_ids = accessible_project_ids(target)

            if not next_project_ids:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="At least one project access is required for non-super_admin users",
                )
            for project_id in next_project_ids:
                self._ensure_actor_can_manage_project(actor, project_id)
            await self._ensure_projects_active(next_project_ids)
            values["project_id"] = next_project_ids[0]

        if values.get("handler_code"):
            existing_by_handler_code = await self.user_repo.get_by_handler_code(
                handler_code=values["handler_code"],
                exclude_user_id=user_id,
            )
            if existing_by_handler_code is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Handler code is already used in this project",
                )

        updated = await self.user_repo.update_user(user_id, **values)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        await self.user_repo.replace_project_accesses(user_id, next_project_ids)
        updated = await self.user_repo.get_by_id(user_id) or updated
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
    def _normalize_project_ids(
        project_ids: list[UUID] | None,
        fallback_project_id: UUID | None,
    ) -> list[UUID]:
        normalized: list[UUID] = []
        for project_id in project_ids or []:
            if project_id not in normalized:
                normalized.append(project_id)
        if fallback_project_id is not None and fallback_project_id not in normalized:
            normalized.insert(0, fallback_project_id)
        return normalized

    async def _ensure_projects_active(self, project_ids: list[UUID]) -> None:
        for project_id in project_ids:
            project = await self.project_repo.get_active(project_id)
            if project is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Project does not exist",
                )

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

        actor_project_ids = accessible_project_ids(actor)
        if not actor_project_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with a project",
            )

        if project_id is not None and project_id not in actor_project_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project is not accessible for current user",
            )

        return project_id if project_id is not None else actor_project_ids[0]

    @classmethod
    def _ensure_actor_can_manage_project(cls, actor: User, project_id: UUID) -> None:
        if actor.role_name == RoleName.SUPER_ADMIN:
            return
        if actor.role_name == RoleName.ADMIN and has_project_access(actor, project_id):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project is not manageable for current user",
        )

    @classmethod
    def _ensure_can_manage_target(cls, actor: User, target: User) -> None:
        if target.is_root and not actor.is_root:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Root account cannot be managed by other users",
            )
        target_role = target.role_name
        if actor.role_name == RoleName.SUPER_ADMIN:
            return

        if target_role == RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="super_admin users cannot be managed here",
            )

        if actor.role_name == RoleName.ADMIN:
            target_project_ids = accessible_project_ids(target)
            if not any(has_project_access(actor, project_id) for project_id in target_project_ids):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Target user is outside current admin projects",
                )
            if target_role not in RoleName.ADMIN_MANAGED:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin can manage only manager/buyer/operator users",
                )
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin/admin can manage staff users",
        )
