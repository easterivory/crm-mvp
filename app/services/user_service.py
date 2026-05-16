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
from app.schemas.user import LoginIn, RoleOut, TokenOut, UserCreate, UserOut


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

        if role.name == RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Creating super_admin users is not allowed from staff UI",
            )

        if role.name not in RoleName.STAFF:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Role is not supported for staff users",
            )

        if actor.role_name == RoleName.ADMIN and role.name not in RoleName.ADMIN_MANAGED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin can create only manager/operator users",
            )

        if data.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="project_id is required for non-super_admin users",
            )

        self._ensure_actor_can_manage_project(actor, data.project_id)

        if data.project_id is not None:
            project = await self.project_repo.get_active(data.project_id)
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
                    project_id=data.project_id,
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
        if target_role == RoleName.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="super_admin users cannot be managed here",
            )

        if actor.role_name == RoleName.SUPER_ADMIN:
            return

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
