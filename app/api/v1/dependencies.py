"""
FastAPI dependency providers.

Dependency tree
---------------
bearer_scheme
    └── get_current_user(db, token) → User
            └── get_current_project_id(user) → UUID

Project-bound users receive project_id from their authenticated user context
when they have exactly one project. Multi-project staff and super_admin users
must pass explicit project_id on scoped endpoints.

get_db is imported from app.core.database and re-exported here so routers
have a single import source for all dependencies.
"""
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db  # re-export — routers import from here
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.access_control import resolve_scoped_project_id

__all__ = ["get_db", "get_current_user", "get_current_project_id", "get_current_root_user"]

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Decodes the Bearer JWT and returns the active User ORM object.
    Raises 401 if the token is missing, invalid, expired, or the user
    is soft-deleted.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await UserRepository(db).get_by_id(UUID(user_id))
    if user is None or user.is_deleted:
        raise credentials_exception
    return user


async def get_current_project_id(
    current_user: User = Depends(get_current_user),
    project_id: Optional[UUID] = Query(default=None),
) -> UUID:
    """
    Returns the project_id scoped to the authenticated user.

    super_admin users are global and may access an explicit project_id from
    the request. Project-bound users may only access their own project; an
    explicit different project_id is rejected.
    """
    return resolve_scoped_project_id(current_user, project_id)


async def get_current_root_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow system-destructive operations only for the immutable Root account."""
    if not current_user.is_root:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Root access is required",
        )
    return current_user
