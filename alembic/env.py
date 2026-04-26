"""Alembic environment — async engine via asyncpg."""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic Config ────────────────────────────────────────────────────────────
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import all models so autogenerate can detect them ─────────────────────────
from app.models import *  # noqa: F401, F403 — side-effect: registers all mappers
from app.models.base import Base

target_metadata = Base.metadata

# ── Override sqlalchemy.url from env if DATABASE_URL is set ──────────────────
import os

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    # asyncpg scheme is needed at runtime; Alembic's synchronous runner needs
    # the plain psycopg2 dialect — but since we use run_async_migrations below,
    # asyncpg is fine here too.
    config.set_main_option("sqlalchemy.url", _db_url)


# ── Offline migrations (generate SQL script without a live DB) ────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (run against a live async DB connection) ────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
