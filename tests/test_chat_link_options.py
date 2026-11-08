"""Chat filters must not compute tracking financial/statistical reports."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event

from app.api.v1.dependencies import get_current_user, get_db
from app.api.v1.routers.tracking import v1_router
from app.models import Bot, Project, TrackingLink
from app.services.tracking_service import TrackingService
from test_gambling_offers import PG, fixture


@PG
def test_light_link_options_project_buyer_bot_pagination_privacy_and_constant_queries(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Chat filters called full tracking serialization/statistics")
    monkeypatch.setattr(TrackingService, "_to_read", forbidden)

    async def run():
        async with fixture() as (sessions, pid, actor, _, bid, _):
            async with sessions() as db:
                other = Project(name="Foreign", slug="foreign")
                bot = Bot(project_id=pid, name="Second")
                db.add_all([other, bot]); await db.flush()
                foreign_bot = Bot(project_id=other.id, name="Foreign bot")
                db.add(foreign_bot); await db.flush()
                now = datetime.now(timezone.utc)
                for n in range(100):
                    db.add(TrackingLink(project_id=pid, bot_id=bid if n % 2 else bot.id,
                        name=f"Source {n}", title="" if n == 0 else f"Title {n}",
                        code="" if n == 0 else f"code-{n}", ref_code=f"ref-{n}",
                        buyer_id=actor.id if n < 10 else None, is_active=n != 0,
                        fb_capi_token="must-not-leak", fb_proxy_url="https://private.example.org",
                        created_at=now + timedelta(seconds=n)))
                db.add(TrackingLink(project_id=other.id, bot_id=foreign_bot.id, name="Foreign", title="Foreign", code="foreign", ref_code="foreign"))
                await db.commit()
                second_bid, foreign_pid, foreign_bid = bot.id, other.id, foreign_bot.id

            manager = SimpleNamespace(id=actor.id, role_name="manager", project_id=pid)
            buyer = SimpleNamespace(id=actor.id, role_name="buyer", project_id=pid)
            current_actor = manager
            app = FastAPI(); app.include_router(v1_router, prefix="/api/v1")
            async def user(): return current_actor
            async def database():
                async with sessions() as db: yield db
            app.dependency_overrides[get_current_user] = user
            app.dependency_overrides[get_db] = database
            sql = []
            async with sessions() as db:
                engine = db.bind.sync_engine
                def record(conn, cursor, statement, parameters, context, executemany): sql.append(statement)
                event.listen(engine, "before_cursor_execute", record)
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        response = await client.get("/api/v1/tracking/link-options", params={"project_id": str(pid), "limit": 100})
                        assert response.status_code == 200
                        result = response.json()
                        assert result["total"] == 101 and len(result["items"]) == 100
                        assert all(set(row) == {"id", "title", "code"} for row in result["items"])
                        assert len(sql) <= 3, sql  # project, options, total; independent of page size
                        assert all("tracking_spends" not in statement and "funnel_step_logs" not in statement for statement in sql)
                        assert "must-not-leak" not in response.text and "private.example.org" not in response.text

                        current_actor = buyer
                        result = (await client.get("/api/v1/tracking/link-options", params={"project_id": str(pid)})).json()
                        assert result["total"] == 10
                        assert {"title": "Source 0", "code": "ref-0"} in [{k: row[k] for k in ["title", "code"]} for row in result["items"]]
                        result = (await client.get("/api/v1/tracking/link-options", params={"project_id": str(pid), "bot_id": str(second_bid), "limit": 2, "offset": 2})).json()
                        assert result["total"] == 5 and len(result["items"]) == 2
                        assert all(row["code"] in {"ref-0", "code-2", "code-4", "code-6", "code-8"} for row in result["items"])
                        assert (await client.get("/api/v1/tracking/link-options", params={"project_id": str(foreign_pid)})).status_code == 403
                        assert (await client.get("/api/v1/tracking/link-options", params={"project_id": str(pid), "limit": 101})).status_code == 422
                        assert (await client.get("/api/v1/tracking/link-options", params={"project_id": str(pid), "bot_id": str(foreign_bid)})).status_code == 404
                finally:
                    event.remove(engine, "before_cursor_execute", record)
    asyncio.run(run())
