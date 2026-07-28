from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class AICredentialError(RuntimeError):
    pass


class AICredentialService:
    """Encrypt provider credentials with a deployment-stable application key."""

    def __init__(self) -> None:
        source = settings.AI_CREDENTIAL_ENCRYPTION_KEY or settings.SECRET_KEY
        self._fingerprint_key = hashlib.sha256(
            f"ai-credential-fingerprint:{source}".encode("utf-8")
        ).digest()
        digest = hashlib.sha256(source.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise AICredentialError("API key cannot be empty")
        return self._fernet.encrypt(normalized.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted_value: str | None) -> str:
        if not encrypted_value:
            raise AICredentialError("Provider API key is not configured")
        try:
            return self._fernet.decrypt(encrypted_value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise AICredentialError(
                "Provider API key cannot be decrypted with the current server key"
            ) from exc

    @staticmethod
    def last_four(value: str) -> str:
        normalized = value.strip()
        return normalized[-4:] if normalized else ""

    def fingerprint(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise AICredentialError("API key cannot be empty")
        return hmac.new(
            self._fingerprint_key,
            normalized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
