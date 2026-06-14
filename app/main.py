from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers import (
    analytics,
    assignments,
    auth,
    bots,
    broadcasts,
    buyers,
    chats,
    domains,
    funnels,
    google_sheets,
    health,
    landers,
    leads,
    messages,
    partners,
    projects,
    public_landers,
    snippets,
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
app.include_router(google_sheets.router, prefix=_v1_prefix)
app.include_router(domains.router, prefix=_v1_prefix)
app.include_router(landers.router, prefix=_v1_prefix)
app.include_router(auth.router, prefix=_v1_prefix)
app.include_router(users.router, prefix=_v1_prefix)
app.include_router(buyers.router, prefix=_v1_prefix)
app.include_router(chats.router, prefix=_v1_prefix)
app.include_router(funnels.router, prefix=_v1_prefix)
app.include_router(messages.router, prefix=_v1_prefix)
app.include_router(messages.media_router, prefix=_v1_prefix)
app.include_router(messages.attachments_router, prefix=_v1_prefix)
app.include_router(leads.router, prefix=_v1_prefix)
app.include_router(assignments.router, prefix=_v1_prefix)
app.include_router(tags.router, prefix=_v1_prefix)
app.include_router(tags.project_router, prefix=_v1_prefix)
app.include_router(snippets.router, prefix=_v1_prefix)
app.include_router(partners.router, prefix=f"{_v1_prefix}/partners")
app.include_router(bots.router, prefix=_v1_prefix)
app.include_router(broadcasts.router, prefix=_v1_prefix)
app.include_router(tracking.router, prefix=_v1_prefix)
app.include_router(tracking.v1_router, prefix=_v1_prefix)
app.include_router(analytics.router, prefix=_v1_prefix)
app.include_router(telegram.router, prefix=_v1_prefix)

# Public lander routes must stay last because /{slug} is intentionally broad.
app.include_router(public_landers.router)
