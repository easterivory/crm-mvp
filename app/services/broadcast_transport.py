"""Run-scoped pooled Bot API transport; retries only explicit rate-limit rejections."""
import asyncio
import time

import httpx


class BroadcastHTTPClient(httpx.AsyncClient):
    def __init__(self, *, rate: float, **kwargs):
        super().__init__(**kwargs)
        self.interval = 1 / max(1, min(rate, 25))
        self.gate = asyncio.Lock()
        self.next_request = 0.0
        self.cooldown_until = 0.0
        self.chat_next_request = {}

    async def post(self, *args, **kwargs):
        # Never replay uploads: streams may already be consumed. Subsequent recipients
        # still respect the common cooldown, and the failed upload remains diagnosable.
        attempts = 1 if kwargs.get("files") else 3
        payload = kwargs.get("json") or kwargs.get("data") or {}
        chat_id = payload.get("chat_id")
        for attempt in range(attempts):
            if chat_id is not None:
                delay = self.chat_next_request.get(chat_id, 0) - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
            async with self.gate:
                while True:
                    delay = max(self.next_request, self.cooldown_until,
                                self.chat_next_request.get(chat_id, 0)) - time.monotonic()
                    if delay <= 0:
                        break
                    await asyncio.sleep(delay)
                self.next_request = time.monotonic() + self.interval
                if chat_id is not None:
                    self.chat_next_request[chat_id] = time.monotonic() + 1
            response = await super().post(*args, **kwargs)
            if response.status_code != 429:
                return response
            try:
                retry_after = max(1, int(response.json().get("parameters", {}).get("retry_after", 1)))
            except (ValueError, TypeError, AttributeError):
                retry_after = 1
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + retry_after)
            if attempt + 1 == attempts:
                return response
            await response.aclose()
