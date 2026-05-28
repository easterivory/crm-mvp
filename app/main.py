from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers import (
    assignments,
    bots,
    broadcasts,
    chats,
    funnels,
    health,
    leads,
    messages,
    projects,
    tags,
    telegram,
    tracking,
    users,
)
from app.core.config import settings
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routes ─────────────────────────────────────────────────────────────────
app.include_router(health.router)

_v1_prefix = "/api/v1"

app.include_router(projects.router, prefix=_v1_prefix)
app.include_router(users.router, prefix=_v1_prefix)
app.include_router(chats.router, prefix=_v1_prefix)
app.include_router(funnels.router, prefix=_v1_prefix)
app.include_router(messages.router, prefix=_v1_prefix)
app.include_router(messages.media_router, prefix=_v1_prefix)
app.include_router(leads.router, prefix=_v1_prefix)
app.include_router(assignments.router, prefix=_v1_prefix)
app.include_router(tags.router, prefix=_v1_prefix)
app.include_router(bots.router, prefix=_v1_prefix)
app.include_router(broadcasts.router, prefix=_v1_prefix)
app.include_router(tracking.router, prefix=_v1_prefix)
app.include_router(tracking.v1_router, prefix=_v1_prefix)
app.include_router(telegram.router, prefix=_v1_prefix)
