import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import spa, telegram_contact
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
    postbacks,
    projects,
    public_landers,
    settings as settings_router,
    snippets,
    tags,
    telegram,
    tracking,
    users,
)
from app.core.config import settings
from app.core.logging_config import configure_file_logging
from app.core.redis import close_redis
from app.services.telegram_webhook_sync_service import sync_telegram_webhook_subscriptions


configure_file_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    webhook_sync_task = asyncio.create_task(sync_telegram_webhook_subscriptions())
    yield
    if not webhook_sync_task.done():
        webhook_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await webhook_sync_task
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
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
app.include_router(settings_router.router, prefix=_v1_prefix)
app.include_router(buyers.router, prefix=_v1_prefix)
app.include_router(chats.router, prefix=_v1_prefix)
app.include_router(funnels.router, prefix=_v1_prefix)
app.include_router(messages.router, prefix=_v1_prefix)
app.include_router(messages.media_router, prefix=_v1_prefix)
app.include_router(messages.attachments_router, prefix=_v1_prefix)
app.include_router(messages.scheduled_router, prefix=_v1_prefix)
app.include_router(leads.router, prefix=_v1_prefix)
app.include_router(assignments.router, prefix=_v1_prefix)
app.include_router(tags.router, prefix=_v1_prefix)
app.include_router(tags.project_router, prefix=_v1_prefix)
app.include_router(snippets.router, prefix=_v1_prefix)
app.include_router(partners.router, prefix=f"{_v1_prefix}/partners")
app.include_router(postbacks.router, prefix=_v1_prefix)
app.include_router(postbacks.lead_event_router, prefix=_v1_prefix)
app.include_router(bots.router, prefix=_v1_prefix)
app.include_router(broadcasts.router, prefix=_v1_prefix)
app.include_router(tracking.router, prefix=_v1_prefix)
app.include_router(tracking.v1_router, prefix=_v1_prefix)
app.include_router(analytics.router, prefix=_v1_prefix)
app.include_router(telegram.router, prefix=_v1_prefix)
app.include_router(telegram_contact.router)
app.include_router(postbacks.public_router)

# BrowserRouter pages need an explicit index.html fallback on direct requests.
# Keep these routes before the broad public /{slug} lander route.
app.include_router(spa.router)

# Public lander routes must stay last because /{slug} is intentionally broad.
app.include_router(public_landers.router)
