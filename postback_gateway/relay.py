import asyncio
import hashlib
import hmac
import logging
import random
import re
import time

import httpx

logger = logging.getLogger(__name__)
MANIFEST_PATH = "/internal/postback-relay/manifest"
DELIVERY_PATH = "/internal/postback-relay/deliver"


def headers(secret, method, path, body=b""):
    timestamp = str(int(time.time()))
    message = f"{method}\n{path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}".encode()
    return {"x-relay-timestamp": timestamp,
        "x-relay-signature": hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        "content-type": "application/json"}


class Relay:
    def __init__(self, config, queue, client):
        self.config, self.queue, self.client = config, queue, client

    async def sync(self):
        response = await self.client.get(self.config.crm_origin + MANIFEST_PATH,
            headers=headers(self.config.secret, "GET", MANIFEST_PATH))
        response.raise_for_status()
        data = response.json()
        hashes = data.get("token_hashes")
        if data.get("version") != 1 or not isinstance(hashes, list) or any(
            not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes):
            raise ValueError("Invalid manifest")
        await asyncio.to_thread(self.queue.set_manifest, hashes)

    async def send_one(self):
        row = await asyncio.to_thread(self.queue.claim)
        if not row:
            return False
        try:
            response = await self.client.post(self.config.crm_origin + DELIVERY_PATH,
                content=row["payload"], headers=headers(self.config.secret, "POST", DELIVERY_PATH, row["payload"]))
            if response.status_code == 200:
                ack = response.json()
                if ack.get("delivery_id") != row["id"] or (ack.get("result") or {}).get("status") not in {"processed", "duplicate", "unmatched"}:
                    raise ValueError("Invalid acknowledgement")
                await asyncio.to_thread(self.queue.finish, row["id"], "done", result=ack["result"]["status"])
                logger.info("Relay acknowledged delivery_id=%s status=%s", row["id"], ack["result"]["status"])
                return True
            if response.status_code in {400, 404, 409, 413, 422}:
                await asyncio.to_thread(self.queue.finish, row["id"], "dead", error=f"HTTP {response.status_code}")
                logger.error("Relay rejected delivery_id=%s code=%s", row["id"], response.status_code)
                return True
            # Authentication failures can be repaired without losing accepted events.
            error = f"HTTP {response.status_code}"
            retry_after = response.headers.get("retry-after", "")
            delay = min(3600, max(1, int(retry_after))) if retry_after.isdigit() else 0
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            error, delay = type(exc).__name__, 0
        delay = max(delay, min(300, 2 ** min(row["attempts"] + 1, 8)) + random.random())
        await asyncio.to_thread(self.queue.finish, row["id"], "pending", delay=delay, error=error)
        logger.warning("Relay retry delivery_id=%s reason=%s", row["id"], error)
        return True

    async def sync_loop(self):
        while True:
            try:
                await self.sync()
                await asyncio.to_thread(self.queue.prune)
            except Exception as exc:
                logger.error("Relay manifest sync failed type=%s", type(exc).__name__)
            await asyncio.sleep(30)

    async def send_loop(self):
        while True:
            try:
                worked = await self.send_one()
            except Exception as exc:
                logger.error("Relay queue cycle failed type=%s", type(exc).__name__)
                worked = False
            await asyncio.sleep(self.config.send_interval if worked else 1)
