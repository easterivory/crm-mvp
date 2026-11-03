import asyncio
import hashlib
import json
import sqlite3
import time
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, Request

from postback_gateway.config import Config
from postback_gateway.queue import Queue, IntakeError
from postback_gateway.server import create_app
from postback_gateway.relay import Relay, headers, DELIVERY_PATH
from app.services.postback_relay_service import signature, authenticate
from app.core.config import settings

TOKEN = "t" * 43
SECRET = "test-secret-" * 6


def config(tmp_path, **kwargs):
    return Config(crm_origin="http://crm.test", secret=SECRET, database=str(tmp_path / "queue.sqlite3"), min_free_bytes=0, **kwargs)


def queue(tmp_path, **kwargs):
    q = Queue(config(tmp_path, **kwargs)); q.initialize()
    q.set_manifest([hashlib.sha256(TOKEN.encode()).hexdigest()])
    return q


def test_protocol_auth_tampering_staleness_and_disabled(monkeypatch):
    monkeypatch.setattr(settings, "POSTBACK_RELAY_ENABLED", True)
    monkeypatch.setattr(settings, "POSTBACK_RELAY_SECRET", SECRET)
    async def run():
        body = b'{"id":1}'
        h = headers(SECRET, "POST", DELIVERY_PATH, body)
        assert h["x-relay-signature"] == signature(SECRET, "POST", DELIVERY_PATH, h["x-relay-timestamp"], body)
        async def check(h, raw=body):
            async def receive():
                return {"type": "http.request", "body": raw}
            request = Request({"type": "http", "method": "POST", "path": DELIVERY_PATH,
                "query_string": b"", "headers": [(k.encode(), v.encode()) for k, v in h.items()]}, receive)
            return await authenticate(request)
        assert await check(h) == body
        for changed in ({**h, "x-relay-timestamp": str(int(time.time()) - 120)},
                        {**h, "x-relay-signature": "bad"}, {**h, "x-relay-signature": "0" * 64}):
            with pytest.raises(HTTPException) as error:
                await check(changed)
            assert error.value.status_code == 401
        with pytest.raises(HTTPException):
            await check(h, b'changed')
        monkeypatch.setattr(settings, "POSTBACK_RELAY_ENABLED", False)
        with pytest.raises(HTTPException) as error:
            await check(h)
        assert error.value.status_code == 404
    asyncio.run(run())


def test_intake_validation_commit_and_restart(tmp_path):
    async def run():
        cfg = config(tmp_path)
        app = create_app(cfg, background=False)
        async with app.router.lifespan_context(app):
            q = app.state.queue
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
                assert (await client.get(f"/pb/{TOKEN}")).status_code == 503
                assert (await client.get("/ready")).status_code == 503
                q.set_manifest([hashlib.sha256(TOKEN.encode()).hexdigest()])
                assert (await client.get("/ready")).status_code == 200
                assert (await client.get("/pb/" + "x" * 43)).status_code == 404
                response = await client.get(f"/pb/{TOKEN}", params={"lead_id": "123", "amount": "12.50"})
                assert response.status_code == 200
                delivery_id = response.json()["delivery_id"]
                assert q.stats()["counts"] == {"pending": 1}
                for payload, content_type, code in [(b"{", "application/json", 400), (b"[]", "application/json", 400),
                    (b'{"a":NaN}', "application/json", 400), (b"raw", "text/plain", 415),
                    (b"x" * 65537, "application/json", 413)]:
                    r = await client.post(f"/pb/{TOKEN}", content=payload, headers={"content-type": content_type})
                    assert r.status_code == code
                r = await client.post(f"/pb/{TOKEN}?lead_id=old", data={"lead_id": "new", "amount": "1,50"})
                assert r.status_code == 200
                assert (await client.get(f"/pb/{TOKEN}?q=" + "x" * 9000)).status_code == 413
        restored = Queue(cfg); restored.initialize()
        row = restored.claim()
        assert row["id"] == delivery_id
        body = json.loads(row["payload"])
        assert body["query_payload"]["lead_id"] == "123"
        assert body["request_method"] == "GET"
        with restored.connect() as db:
            db.execute("UPDATE jobs SET lease=0 WHERE id=?", (delivery_id,))
        assert restored.claim()["id"] == delivery_id
    asyncio.run(run())


def test_queue_full_stale_manifest_rotation_and_pruning(tmp_path):
    q = queue(tmp_path, max_jobs=1)
    first = q.enqueue(TOKEN, "GET", {}, {})
    with pytest.raises(IntakeError) as error:
        q.enqueue(TOKEN, "GET", {}, {})
    assert error.value.status == 503
    q.finish(first, "dead", error="HTTP 404")
    q.prune()
    assert q.stats()["counts"]["dead"] == 1
    assert q.retry(first) == 1
    assert q.claim()["id"] == first
    q.set_manifest([])
    with pytest.raises(IntakeError) as error:
        q.check_token(TOKEN)
    assert error.value.status == 404
    with q.connect() as db:
        db.execute("UPDATE metadata SET value='0' WHERE key='manifest_at'")
    with pytest.raises(IntakeError) as error:
        q.check_token(TOKEN)
    assert error.value.status == 503


@pytest.mark.parametrize("code,status", [(400, "dead"), (404, "dead"), (409, "dead"), (422, "dead"),
    (401, "pending"), (403, "pending"), (429, "pending"), (500, "pending"), (302, "pending")])
def test_delivery_failures_are_retained(tmp_path, code, status):
    async def run():
        q = queue(tmp_path); delivery_id = q.enqueue(TOKEN, "POST", {}, {"lead_id": "1"})
        async def respond(request):
            return httpx.Response(code, headers={"retry-after": "60"}, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await Relay(config(tmp_path), q, client).send_one()
        with q.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (delivery_id,)).fetchone()
            assert row["status"] == status and row["attempts"] == 1
            if status == "pending":
                assert row["due"] > time.time()
    asyncio.run(run())


def test_transport_timeout_and_invalid_ack_never_drop_event(tmp_path):
    async def run():
        q = queue(tmp_path); delivery_id = q.enqueue(TOKEN, "GET", {}, {})
        async def respond(request):
            raise httpx.ReadTimeout("response lost")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await Relay(config(tmp_path), q, client).send_one()
        with q.connect() as db:
            db.execute("UPDATE jobs SET due=0")
        async def bad_ack(request):
            return httpx.Response(200, json={"delivery_id": str(uuid4()), "result": {"status": "processed"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(bad_ack)) as client:
            assert await Relay(config(tmp_path), q, client).send_one()
        with q.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (delivery_id,)).fetchone()
            assert row["status"] == "pending" and row["attempts"] == 2
    asyncio.run(run())


def test_parallel_admission_enforces_capacity(tmp_path):
    async def run():
        q = queue(tmp_path, max_jobs=3)
        results = await asyncio.gather(*(asyncio.to_thread(q.enqueue, TOKEN, "GET", {}, {}) for _ in range(10)), return_exceptions=True)
        assert sum(isinstance(r, str) for r in results) == 3
        assert sum(isinstance(r, IntakeError) for r in results) == 7
    asyncio.run(run())


def test_public_url_and_scoped_mode_are_backward_compatible(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services.postback_endpoint_service import PostbackEndpointService
    from app.services.postback_relay_service import public_base_url
    pid = uuid4()
    endpoint = SimpleNamespace(id=uuid4(), project_id=pid, partner_integration_id=None,
        name="QA", event_type="registration", parameter_mapping={}, is_active=True,
        secret_token=TOKEN, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    monkeypatch.setattr(settings, "BASE_URL", "https://crm.invalid")
    monkeypatch.setattr(settings, "POSTBACK_PUBLIC_BASE_URL", "https://callbacks.invalid")
    monkeypatch.setattr(settings, "POSTBACK_RELAY_ENABLED", False)
    service = PostbackEndpointService(None)
    assert service._endpoint_out(endpoint).url.startswith("https://crm.invalid/pb/")
    monkeypatch.setattr(settings, "POSTBACK_RELAY_ENABLED", True)
    monkeypatch.setattr(settings, "POSTBACK_RELAY_SECRET", SECRET)
    monkeypatch.setattr(settings, "POSTBACK_RELAY_PROJECT_IDS", str(pid))
    result = service._endpoint_out(endpoint)
    assert result.delivery_mode == "relay" and result.url == f"https://callbacks.invalid/pb/{TOKEN}"
    monkeypatch.setattr(settings, "POSTBACK_RELAY_PROJECT_IDS", str(uuid4()))
    assert service._endpoint_out(endpoint).delivery_mode == "direct"
    for invalid in ["http://insecure.invalid", "https://user:password@host", "https://host/path", "https://host?query=1"]:
        monkeypatch.setattr(settings, "POSTBACK_PUBLIC_BASE_URL", invalid)
        with pytest.raises(HTTPException):
            public_base_url()


def test_gateway_deployment_is_separate_and_has_no_crm_imports():
    from pathlib import Path
    import ast
    root = Path(__file__).resolve().parents[1]
    assert "postback_gateway/" in (root / ".dockerignore").read_text()
    assert "postback_gateway" not in (root / "docker-compose.yml").read_text()
    assert "compose.gateway" not in (root / "deploy-dev.sh").read_text()
    for source in (root / "postback_gateway").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.")
            if isinstance(node, ast.Import):
                assert not any(alias.name == "app" or alias.name.startswith("app.") for alias in node.names)


def test_nginx_gateway_example_is_valid(tmp_path):
    from pathlib import Path
    import shutil
    import subprocess
    nginx = shutil.which("nginx") or "/opt/homebrew/opt/nginx/bin/nginx"
    if not Path(nginx).is_file() or not shutil.which("openssl"):
        pytest.skip("Local nginx and openssl required")
    cert, key = tmp_path / "test.crt", tmp_path / "test.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=postbacks.invalid", "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    sample = (Path(__file__).resolve().parents[1] / "postback_gateway/nginx.gateway.conf.example").read_text()
    sample = sample.replace("/etc/letsencrypt/live/postbacks.example.com/fullchain.pem", str(cert)).replace(
        "/etc/letsencrypt/live/postbacks.example.com/privkey.pem", str(key))
    configuration = tmp_path / "nginx.conf"
    configuration.write_text(f"error_log stderr; pid {tmp_path}/nginx.pid; events {{}} http {{ access_log off; {sample} }}")
    subprocess.run([nginx, "-t", "-p", str(tmp_path), "-c", str(configuration)], check=True, capture_output=True)


def test_main_route_ack_requires_commit_and_rejects_bad_auth(monkeypatch, caplog):
    from unittest.mock import AsyncMock
    from fastapi import FastAPI
    from app.api.v1.dependencies import get_db
    from app.api.v1.routers import postback_relay
    monkeypatch.setattr(settings, "POSTBACK_RELAY_ENABLED", True)
    monkeypatch.setattr(settings, "POSTBACK_RELAY_SECRET", SECRET)
    async def run():
        db = AsyncMock()
        result = {"status": "processed", "receipt_id": str(uuid4()), "event_id": str(uuid4())}
        delivery = AsyncMock(return_value=result)
        monkeypatch.setattr(postback_relay, "deliver", delivery)
        app = FastAPI(); app.include_router(postback_relay.router)
        async def dependency():
            yield db
        app.dependency_overrides[get_db] = dependency
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://crm.test") as client:
            body = json.dumps({"delivery_id": str(uuid4()), "secret_token": TOKEN, "request_method": "GET",
                "query_payload": {"lead_id": "1"}, "body_payload": {}}).encode()
            assert (await client.post(DELIVERY_PATH, content=body)).status_code == 401
            delivery.assert_not_awaited()
            response = await client.post(DELIVERY_PATH, content=body, headers=headers(SECRET, "POST", DELIVERY_PATH, body))
            assert response.status_code == 200
            db.commit.assert_awaited_once()
            assert response.json()["result"] == result
            db.commit.side_effect = RuntimeError(f"Sensitive DB failure {TOKEN}")
            response = await client.post(DELIVERY_PATH, content=body, headers=headers(SECRET, "POST", DELIVERY_PATH, body))
            assert response.status_code == 503
            db.rollback.assert_awaited_once()
            assert TOKEN not in response.text and TOKEN not in caplog.text
    asyncio.run(run())


def test_queue_backup_is_restorable_and_private(tmp_path, monkeypatch):
    from postback_gateway.admin import main
    q = queue(tmp_path)
    q.enqueue(TOKEN, "GET", {"lead_id": "test"}, {})
    destination = tmp_path / "backup.sqlite3"
    monkeypatch.setenv("CRM_ORIGIN", "http://crm.test")
    monkeypatch.setenv("RELAY_SECRET", SECRET)
    monkeypatch.setenv("QUEUE_DATABASE", str(q.path))
    monkeypatch.setattr("sys.argv", ["admin", "backup", str(destination)])
    main()
    assert destination.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(destination) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(SystemExit):
        main()
