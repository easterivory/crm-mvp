"""Run only against an explicitly supplied disposable local PostgreSQL instance."""
import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import *  # noqa: F403 - register the complete schema
from app.models.base import Base
from app.models.lander import ProjectDomain, ProjectLander
from app.models.project import Project
from app.models.user import User
from app.models.role import Role
from app.schemas.lander import ProjectDomainCreate
from app.services.lander_admin_service import LanderAdminService
from app.services.lander_service import LanderService


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL URL not provided")
def test_shared_domain_upgrade_routing_deletion_and_safe_downgrade():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = f"check_0077_{uuid4().hex}"
        admin = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        spec = importlib.util.spec_from_file_location("migration_0077", Path(__file__).resolve().parents[1] / "alembic/versions/20260916_0077_push_photos_shared_domains.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        def migrate(conn, direction):
            with Operations.context(MigrationContext.configure(conn)):
                getattr(migration, direction)()

        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Build the predecessor schema without changing historical migrations.
                await conn.run_sync(migrate, "downgrade")
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                p1, p2 = Project(name="First", slug="first"), Project(name="Second", slug="second")
                db.add_all([p1, p2])
                await db.flush()
                old = ProjectDomain(project_id=p1.id, domain_name="shared.example.com")
                db.add(old)
                await db.commit()
                p1_id, p2_id, old_id = p1.id, p2.id, old.id
            async with engine.begin() as conn:
                await conn.run_sync(migrate, "upgrade")
            async with sessions() as db:
                service = LanderAdminService(db)
                actor = User(role=Role(name="super_admin"))
                shared = await service.create_domain(project_id=p2_id,
                    data=ProjectDomainCreate(domain_name="shared.example.com"), actor=actor)
                assert shared.id != old_id
                one = ProjectLander(project_id=p1_id, domain_id=old_id, name="One", type="default_tg_redirect", slug="one")
                two = ProjectLander(project_id=p2_id, domain_id=shared.id, name="Two", type="default_tg_redirect", slug="two")
                db.add_all([one, two])
                await db.commit()
                assert (await LanderService(db).resolve_lander_request("shared.example.com", "one")).project_id == p1_id
                assert (await LanderService(db).resolve_lander_request("shared.example.com", "two")).project_id == p2_id
                await service.delete_domain(project_id=p1_id, domain_id=old_id, actor=actor)
                await db.commit()
                assert (await LanderService(db).resolve_lander_request("shared.example.com", "two")).project_id == p2_id
            with pytest.raises(Exception, match="Remove duplicate project domain bindings"):
                async with engine.begin() as conn:
                    await conn.run_sync(migrate, "downgrade")
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE project_domains SET domain_name='second.example.com' WHERE id=:id"), {"id": shared.id})
                await conn.run_sync(migrate, "downgrade")
                await conn.run_sync(migrate, "upgrade")
                assert (await conn.execute(text("SELECT count(*) FROM project_domains"))).scalar_one() == 2
        finally:
            await engine.dispose()
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await admin.dispose()

    asyncio.run(run())
