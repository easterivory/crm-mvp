import asyncio
from contextlib import asynccontextmanager
import json
import re
import sqlite3
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, HTTPException, Request

from .config import Config
from .queue import Queue, IntakeError
from .relay import Relay


def create_app(config=None, *, background=True):
    config = config or Config.from_env()
    config.validate()
    queue = Queue(config)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(queue.initialize)
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=3), follow_redirects=False, trust_env=False) as client:
            relay = Relay(config, queue, client)
            tasks = [asyncio.create_task(relay.sync_loop()), asyncio.create_task(relay.send_loop())] if background else []
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.queue = queue

    @app.get("/health")
    async def health():
        return {"status": "up"}

    @app.get("/ready")
    async def ready():
        try:
            state = await asyncio.to_thread(queue.stats)
        except (sqlite3.Error, OSError):
            raise HTTPException(503) from None
        age = state["manifest_age_seconds"]
        backlog = sum(n for status, n in state["counts"].items() if status != "done")
        if age is None or age > config.manifest_ttl or state["free_bytes"] < config.min_free_bytes or backlog >= config.max_jobs:
            raise HTTPException(503, "Intake unavailable")
        return {"status": "ready"}

    @app.api_route("/pb/{token}", methods=["GET", "POST"])
    async def receive(token: str, request: Request):
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise HTTPException(404)
        try:
            await asyncio.to_thread(queue.check_token, token)
            query_raw = request.scope.get("query_string", b"")
            if len(query_raw) > 8192:
                raise HTTPException(413)
            query = dict(parse_qsl(query_raw.decode("utf-8"), keep_blank_values=True, max_num_fields=100))
            raw = bytearray()
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise HTTPException(413)
            body = {}
            if request.method == "POST" and raw:
                content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type == "application/json":
                    body = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                    if not isinstance(body, dict):
                        raise HTTPException(400, "JSON object required")
                elif content_type == "application/x-www-form-urlencoded":
                    body = dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=100))
                else:
                    raise HTTPException(415, "Use JSON or URL-encoded form")
            delivery_id = await asyncio.to_thread(queue.enqueue, token, request.method, query, body)
        except IntakeError as exc:
            raise HTTPException(exc.status, "Postback unavailable") from None
        except TimeoutError:
            raise HTTPException(408) from None
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, "Invalid payload") from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, "Durable queue unavailable") from None
        return {"status": "accepted", "delivery_id": delivery_id}

    return app
