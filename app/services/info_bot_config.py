"""Independent opt-in info bot configuration; credentials never returned to UI."""
import json

from app.services.ai_credential_service import AICredentialService
from app.services.system_setting_service import SystemSettingService

INFO_BOT_KEY = "info_bot_config_v1"


class InfoBotConfigService:
    def __init__(self, db):
        self.settings = SystemSettingService(db)

    async def read(self) -> dict:
        return json.loads(await self.settings.get_value(INFO_BOT_KEY) or "{}")

    async def token(self) -> str | None:
        config = await self.read()
        return AICredentialService().decrypt(config["encrypted_token"]) if config.get("enabled") and config.get("encrypted_token") else None

    @staticmethod
    def public(config: dict) -> dict:
        return {"enabled": bool(config.get("enabled")), "has_token": bool(config.get("encrypted_token")),
                "username": config.get("username")}
