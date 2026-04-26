"""
FastAPI dependency providers.

Dependency tree
---------------
bearer_scheme
    └── get_current_user(db, token) → User
            └── get_current_project_id(user) → UUID

All endpoints receive project_id from the authenticated user's context —
it is never accepted as a query/path/body parameter. This ensures one user
cannot access another project's data by supplying an arbitrary UUID.

get_db is imported from app.core.database and re-exported here so routers
have a single import source for all dependencies.
"""
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db  # re-export — routers import from here
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

__all__ = ["get_db", "get_current_user", "get_current_project_id"]

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


# SECURITY: project_id is never accepted from request (query / path / body).
# It is always derived from the authenticated user's JWT via this dependency.
# This prevents cross-project data access by supplying an arbitrary UUID.
async def get_current_project_id(
    current_user: User = Depends(get_current_user),
) -> UUID:
    """
    Returns the project_id scoped to the authenticated user.

    Raises 403 if the user has no project (super_admin case — not handled
    in Phase 2; super_admin endpoints will require their own dependency that
    accepts an explicit project_id once multi-tenancy support is added).
    """
    if current_user.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a project",
        )
    return current_user.project_id
