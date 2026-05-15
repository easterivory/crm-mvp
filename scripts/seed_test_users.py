"""
Idempotently seed test users for local frontend/backend auth checks.

Usage:
    python scripts/seed_test_users.py

Optional env vars:
    TEST_PROJECT_NAME="Test CRM Project"
    TEST_ADMIN_PASSWORD="AdminPass123!"
    TEST_MANAGER_PASSWORD="ManagerPass123!"
    TEST_SUPER_ADMIN_PASSWORD="SuperAdminPass123!"
"""
import asyncio
import os
import re
import sys
import unicodedata
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.constants import RoleName
from app.core.config import settings
from app.core.database import get_db_session
from app.core.security import hash_password
from app.models.project import Project
from app.models.role import Role
from app.models.user import User


DEFAULT_PROJECT_NAME = "Test CRM Project"

DEFAULT_SUPER_ADMIN_EMAIL = "superadmin@testcrm.dev"
DEFAULT_SUPER_ADMIN_NAME = "Super Admin"
DEFAULT_SUPER_ADMIN_PASSWORD = "SuperAdminPass123!"

DEFAULT_ADMIN_EMAIL = "admin@testcrm.dev"
DEFAULT_ADMIN_NAME = "Project Admin"
DEFAULT_ADMIN_PASSWORD = "AdminPass123!"

DEFAULT_MANAGER_EMAIL = "manager@testcrm.dev"
DEFAULT_MANAGER_NAME = "Project Manager"
DEFAULT_MANAGER_PASSWORD = "ManagerPass123!"


def _slugify_project_name(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "project"


async def _get_or_create_project(db) -> Project:
    project_id = os.getenv("TELEGRAM_PROJECT_ID") or settings.TELEGRAM_PROJECT_ID
    project_name = os.getenv("TEST_PROJECT_NAME", DEFAULT_PROJECT_NAME)
    if project_id:
        project = await db.get(Project, UUID(project_id))
        if project is not None and project.is_deleted:
            raise RuntimeError(f"Project is deleted: {project_id}")
        if project is not None:
            return project

        project = Project(
            id=UUID(project_id),
            name=project_name,
            slug=_slugify_project_name(project_name),
            sla_threshold_minutes=30,
        )
        db.add(project)
        await db.flush()
        await db.refresh(project)
        return project

    result = await db.execute(
        select(Project).where(Project.name == project_name, Project.is_deleted.is_(False))
    )
    project = result.scalar_one_or_none()
    if project is not None:
        return project

    project = Project(
        name=project_name,
        slug=_slugify_project_name(project_name),
        sla_threshold_minutes=30,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _get_role_by_name(db, role_name: str) -> Role:
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        raise RuntimeError(
            f"Role '{role_name}' not found. Run migrations first: alembic upgrade head"
        )
    return role


async def _upsert_user(
    db,
    *,
    email: str,
    name: str,
    password: str,
    role_id,
    project_id,
) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            name=name,
            password_hash=hash_password(password),
            role_id=role_id,
            project_id=project_id,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    user.name = name
    user.password_hash = hash_password(password)
    user.role_id = role_id
    user.project_id = project_id
    user.is_deleted = False
    await db.flush()
    return user


async def main() -> None:
    super_admin_password = os.getenv("TEST_SUPER_ADMIN_PASSWORD", DEFAULT_SUPER_ADMIN_PASSWORD)
    admin_password = os.getenv("TEST_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    manager_password = os.getenv("TEST_MANAGER_PASSWORD", DEFAULT_MANAGER_PASSWORD)

    async with get_db_session() as db:
        try:
            project = await _get_or_create_project(db)

            super_admin_role = await _get_role_by_name(db, RoleName.SUPER_ADMIN)
            admin_role = await _get_role_by_name(db, RoleName.ADMIN)
            manager_role = await _get_role_by_name(db, RoleName.MANAGER)

            super_admin = await _upsert_user(
                db,
                email=DEFAULT_SUPER_ADMIN_EMAIL,
                name=DEFAULT_SUPER_ADMIN_NAME,
                password=super_admin_password,
                role_id=super_admin_role.id,
                project_id=None,
            )
            admin = await _upsert_user(
                db,
                email=DEFAULT_ADMIN_EMAIL,
                name=DEFAULT_ADMIN_NAME,
                password=admin_password,
                role_id=admin_role.id,
                project_id=project.id,
            )
            manager = await _upsert_user(
                db,
                email=DEFAULT_MANAGER_EMAIL,
                name=DEFAULT_MANAGER_NAME,
                password=manager_password,
                role_id=manager_role.id,
                project_id=project.id,
            )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    print("Seeded test users (idempotent)")
    print(f"project_id={project.id}")
    print(f"super_admin: {super_admin.email} / {super_admin_password}")
    print(f"admin:       {admin.email} / {admin_password}")
    print(f"manager:     {manager.email} / {manager_password}")


if __name__ == "__main__":
    asyncio.run(main())
