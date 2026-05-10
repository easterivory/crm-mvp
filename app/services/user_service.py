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
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[UserOut], int]:
        users = await self.user_repo.list_by_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        total = await self.user_repo.count_by_project(project_id)
        return [UserOut.model_validate(user) for user in users], total

    async def list_roles(self) -> list[RoleOut]:
        roles = await self.user_repo.list_roles()
        return [RoleOut.model_validate(role) for role in roles]

    async def create_user(self, data: UserCreate) -> UserOut:
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
            if data.project_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="super_admin user must not be associated with a project",
                )
        elif data.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="project_id is required for non-super_admin users",
            )

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

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()
