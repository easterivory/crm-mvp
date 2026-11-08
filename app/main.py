import asyncio
import logging
import time
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api import spa, telegram_contact
from app.api.v1.routers import (
    traffic_quality,
    analytics,
    ai,
    assignments,
    auth,
    bots,
    broadcasts,
    buyers,
    channel_tracking,
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
    tiktok,
    info_bot,
    advertising,
    users,
)
from app.core.config import settings
from app.core.logging_config import configure_file_logging
from app.core.redis import close_redis
from app.core.arq_client import close_arq_client
from app.services.telegram_webhook_sync_service import sync_telegram_webhook_subscriptions


configure_file_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.chat_lease_maintenance_service import run_chat_lease_maintenance
    webhook_sync_task = asyncio.create_task(sync_telegram_webhook_subscriptions())
    lease_task = asyncio.create_task(run_chat_lease_maintenance(), name="chat-lease-maintenance")
    try:
        yield
    finally:
        for task in (lease_task, webhook_sync_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(lease_task, webhook_sync_task, return_exceptions=True)
        from app.services.chat_workspace_counts_service import close_counter_refreshes
        await close_counter_refreshes()
        await close_redis()
        await close_arq_client()
        from app.core.assistant import close_assistant_db
        await close_assistant_db()
        from app.core.telegram_intake import close_reserved_db_pools
        await close_reserved_db_pools()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_unhandled_request_errors(request: Request, call_next):
    started = time.monotonic()
    request_id = uuid4().hex
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        if request.url.path == "/api/v1/chats/workspace-counts":
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Authorization"
        return response
    except Exception:
        # Uvicorn's error logger does not propagate into the bounded application
        # log file used by the super-admin export. Keep request bodies and query
        # strings out of this record because they can contain credentials.
        logger.exception(
            "Unhandled API request error method=%s path=%s",
            request.method,
            "/pb/[redacted]" if request.url.path.startswith("/pb/") else request.url.path,
        )
        raise
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms >= 1000 or status_code >= 500:
            logger.warning("API request timing request_id=%s method=%s route=%s status=%s elapsed_ms=%s",
                request_id, request.method, getattr(request.scope.get("route"), "path", "unmatched"), status_code, elapsed_ms)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from app.core.assistant_boundary import AssistantBoundaryMiddleware
app.add_middleware(AssistantBoundaryMiddleware)

# ─── Routes ─────────────────────────────────────────────────────────────────
app.include_router(health.router)
from app.api.v1.routers import assistant
app.include_router(assistant.router)
app.include_router(assistant.oauth_router)

_v1_prefix = "/api/v1"

app.include_router(projects.router, prefix=_v1_prefix)
app.include_router(google_sheets.router, prefix=_v1_prefix)
app.include_router(domains.router, prefix=_v1_prefix)
app.include_router(landers.router, prefix=_v1_prefix)
app.include_router(auth.router, prefix=_v1_prefix)
app.include_router(users.router, prefix=_v1_prefix)
app.include_router(settings_router.router, prefix=_v1_prefix)
app.include_router(buyers.router, prefix=_v1_prefix)
app.include_router(channel_tracking.router, prefix=_v1_prefix)
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
from app.api.v1.routers import gambling_offers
app.include_router(gambling_offers.router, prefix=_v1_prefix)
app.include_router(gambling_offers.lead_router, prefix=_v1_prefix)
app.include_router(bots.router, prefix=_v1_prefix)
app.include_router(broadcasts.router, prefix=_v1_prefix)
app.include_router(tracking.router, prefix=_v1_prefix)
app.include_router(tracking.v1_router, prefix=_v1_prefix)
app.include_router(tiktok.router, prefix=_v1_prefix)
app.include_router(info_bot.router, prefix=_v1_prefix)
app.include_router(advertising.router, prefix=_v1_prefix)
app.include_router(traffic_quality.router, prefix=_v1_prefix)
app.include_router(analytics.router, prefix=_v1_prefix)
app.include_router(ai.router, prefix=_v1_prefix)
app.include_router(telegram.router, prefix=_v1_prefix)
app.include_router(telegram_contact.router)
app.include_router(postbacks.public_router)
from app.api.v1.routers import postback_relay
app.include_router(postback_relay.router)

# BrowserRouter pages need an explicit index.html fallback on direct requests.
# Keep these routes before the broad public /{slug} lander route.
app.include_router(spa.router)

# Public lander routes must stay last because /{slug} is intentionally broad.
app.include_router(public_landers.router)
