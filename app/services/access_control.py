from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from app.core.constants import RoleName
from app.models.user import User


def accessible_project_ids(user: User) -> list[UUID]:
    accesses = user.__dict__.get("project_accesses")
    if accesses is None:
        return [user.project_id] if user.project_id is not None else []

    ids: list[UUID] = []
    if user.project_id is not None:
        ids.append(user.project_id)
    for access in accesses:
        if access.project_id not in ids:
            ids.append(access.project_id)
    return ids


def has_project_access(user: User, project_id: UUID) -> bool:
    if user.role_name == RoleName.SUPER_ADMIN:
        return True
    return project_id in accessible_project_ids(user)


def require_project_access(user: User, project_id: UUID) -> None:
    if has_project_access(user, project_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Project is not accessible for current user",
    )


def resolve_scoped_project_id(user: User, requested_project_id: UUID | None) -> UUID:
    if user.role_name == RoleName.SUPER_ADMIN:
        if requested_project_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="project_id is required for super_admin scoped requests",
            )
        return requested_project_id

    project_ids = accessible_project_ids(user)
    if not project_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a project",
        )

    if requested_project_id is not None:
        require_project_access(user, requested_project_id)
        return requested_project_id

    if len(project_ids) == 1:
        return project_ids[0]

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="project_id is required for multi-project users",
    )
