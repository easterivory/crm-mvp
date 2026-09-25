"""Explicit one-time migration of the configured backup bot to a local API."""
from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.core.database import get_db_session
from app.services.system_setting_service import SystemSettingService


async def migrate(*, logout_cloud: bool) -> None:
    base = settings.BACKUP_TELEGRAM_API_BASE_URL.rstrip("/")
    if urlsplit(base).hostname in {None, "api.telegram.org"}:
        raise RuntimeError("Configure the local BACKUP_TELEGRAM_API_BASE_URL first")
    async with get_db_session() as db:
        service = SystemSettingService(db)
        config = await service.get_effective_global_config()
        buyer = await service.get_effective_buyer_bot_config()
    token = config.tg_backup_bot_token
    if not token:
        raise RuntimeError("Configure the backup bot in CRM system settings first")
    if token in {config.admin_bot_token, buyer.token}:
        raise RuntimeError("Backup bot must not also be the admin or buyer bot")

    async with httpx.AsyncClient(timeout=60) as client:
        async def call(api: str, method: str) -> dict:
            response = await client.post(f"{api}/bot{token}/{method}")
            data = response.json()
            if response.is_error or not data.get("ok"):
                # Never print the request URL: it contains the bot token.
                raise RuntimeError(f"{method} failed (HTTP {response.status_code}); check bot/API configuration")
            return data

        if logout_cloud:
            # Check reachability before disabling the currently working cloud session.
            probe = await client.get(base)
            if probe.status_code >= 500:
                raise RuntimeError("Local API is unavailable; cloud session was not changed")
            info = await call("https://api.telegram.org", "getWebhookInfo")
            if info["result"].get("url"):
                raise RuntimeError("This bot has an active webhook. Use a dedicated backup bot; migration stopped")
            await call("https://api.telegram.org", "logOut")
            print("Backup bot logged out of cloud API. Cloud login is unavailable for 10 minutes.")
        me = await call(base, "getMe")
        print(f"Local API ready for backup bot @{me['result']['username']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logout-cloud", action="store_true", help="One-time cloud logout before local use")
    args = parser.parse_args()
    try:
        asyncio.run(migrate(logout_cloud=args.logout_cloud))
    except Exception as exc:
        # HTTP exceptions include credentials in their URLs; only expose safe errors.
        parser.exit(1, f"{str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}\n")
