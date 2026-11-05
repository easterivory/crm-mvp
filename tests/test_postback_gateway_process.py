"""Real HTTP acknowledgement followed by SIGKILL, with SQLite recovery on restart."""
import hashlib
import json
import multiprocessing
import socket
import time
from uuid import uuid4

import httpx

from postback_gateway.config import Config
from postback_gateway.queue import Queue


def serve(config, port):
    import uvicorn
    from postback_gateway.server import create_app
    uvicorn.run(create_app(config, background=False), host="127.0.0.1", port=port,
        log_level="error", access_log=False)


def wait_ready(port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/ready", timeout=.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.05)
    raise AssertionError("Gateway did not become ready")


def test_ack_sigkill_restart_and_claim_recovery(tmp_path):
    token = "p" * 43
    config = Config(crm_origin="http://crm.invalid", secret="test-key-" * 8,
        database=str(tmp_path / "queue.sqlite3"), min_free_bytes=0)
    queue = Queue(config); queue.initialize()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    queue.set_manifest([token_hash], {token_hash: {"endpoint_id": str(uuid4()), "revision": 3, "ack_text": "OK"}})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    process = None
    try:
        process = multiprocessing.get_context("spawn").Process(target=serve, args=(config, port))
        process.start(); wait_ready(port)
        response = httpx.post(f"http://127.0.0.1:{port}/pb/{token}", json={"lead_id": str(uuid4()), "event_id": "accepted-before-crash"})
        assert response.status_code == 200 and response.text == "OK"
        process.kill(); process.join(timeout=5)
        assert not process.is_alive()
        first = queue.claim()
        assert first is not None
        envelope = json.loads(first["payload"])
        assert envelope["endpoint_revision"] == 3 and envelope["received_at"]
        # Simulate a worker that died after claim but before acknowledgement.
        with queue.connect() as db: db.execute("UPDATE jobs SET lease=0")
        process = multiprocessing.get_context("spawn").Process(target=serve, args=(config, port))
        process.start(); wait_ready(port)
        recovered = queue.claim()
        assert recovered["id"] == first["id"] and recovered["payload"] == first["payload"]
        assert recovered["attempts"] == 1
        queue.finish(recovered["id"], "done", result="processed")
        assert queue.stats()["counts"] == {"done": 1}
    finally:
        if process and process.is_alive():
            process.terminate(); process.join(timeout=5)
            if process.is_alive(): process.kill(); process.join(timeout=5)
