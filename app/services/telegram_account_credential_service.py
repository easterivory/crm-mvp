from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TelegramAccountCredentialError(RuntimeError):
    pass


class TelegramAccountCredentialService:
    """Encrypt MTProto API hashes, login state and persistent sessions at rest."""

    def __init__(self) -> None:
        source = settings.TELEGRAM_ACCOUNT_ENCRYPTION_KEY or settings.SECRET_KEY
        digest = hashlib.sha256(source.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise TelegramAccountCredentialError("Telegram credential cannot be empty")
        return self._fernet.encrypt(normalized.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted_value: str | None, *, label: str) -> str:
        if not encrypted_value:
            raise TelegramAccountCredentialError(f"Telegram {label} is not configured")
        try:
            return self._fernet.decrypt(encrypted_value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise TelegramAccountCredentialError(
                f"Telegram {label} cannot be decrypted with the current server key"
            ) from exc

    @staticmethod
    def last_four(value: str) -> str:
        normalized = value.strip()
        return normalized[-4:] if normalized else ""
