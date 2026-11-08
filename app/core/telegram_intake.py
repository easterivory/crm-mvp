"""Small reserved pools: intake cannot queue behind expensive UI aggregates."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings


_factories = {}


def _sessions(purpose):
    if purpose in _factories: return _factories[purpose]
    intake = purpose == "intake"
    server_settings = {"statement_timeout": "3000", "lock_timeout": "1000"}
    if not intake: server_settings["default_transaction_read_only"] = "on"
    engine = create_async_engine(settings.DATABASE_URL, pool_size=2 if intake else 1,
        max_overflow=0, pool_timeout=0.5, pool_pre_ping=True, hide_parameters=True,
        connect_args={"timeout": 2, "server_settings": server_settings})
    _factories[purpose] = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return _factories[purpose]


def get_intake_db_session(): return _sessions("intake")()


def get_count_db_session(): return _sessions("counts")()


async def close_reserved_db_pools():
    # Do not initialize unused pools during shutdown (workers never use them).
    factories = list(_factories.values())
    _factories.clear()
    for factory in factories: await factory.kw["bind"].dispose()
