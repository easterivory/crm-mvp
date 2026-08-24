from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    ApiIdPublishedFloodError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from app.core.config import settings
from app.models.bot import Bot, TelegramUserConnection
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.telegram_user_connection_repository import (
    TelegramUserConnectionRepository,
)
from app.schemas.bot import (
    TelegramAccountConnectIn,
    TelegramAccountConnectionOut,
)
from app.services.telegram_account_credential_service import (
    TelegramAccountCredentialError,
    TelegramAccountCredentialService,
)


class TelegramUserAccountService:
    """Authorize and manage one dedicated MTProto work account per CRM bot row."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.connection_repo = TelegramUserConnectionRepository(db)
        self.credentials = TelegramAccountCredentialService()

    async def get_status(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
    ) -> TelegramAccountConnectionOut:
        bot = await self._get_account_bot(bot_id, project_id)
        connection = await self.connection_repo.get_by_bot_id(bot.id)
        return self._status_out(bot.id, connection)

    async def request_login_code(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        data: TelegramAccountConnectIn,
        actor: User,
    ) -> TelegramAccountConnectionOut:
        bot = await self._get_account_bot(bot_id, project_id)
        phone_number = self._normalize_phone(data.phone_number)
        api_hash = data.api_hash.strip()
        api_hash_encrypted = self.credentials.encrypt(api_hash)

        connection = await self.connection_repo.get_by_bot_id(bot.id)
        if connection is not None and connection.auth_status == "authorized":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Сначала отключите текущую Telegram-сессию, затем подключите аккаунт заново.",
            )
        values = {
            "api_id": data.api_id,
            "api_hash_encrypted": api_hash_encrypted,
            "api_hash_last_four": self.credentials.last_four(api_hash),
            "phone_number": phone_number,
            "auth_status": "disconnected",
            "connection_status": "disconnected",
            "session_encrypted": None,
            "phone_code_hash_encrypted": None,
            "auth_expires_at": None,
            "last_error": None,
        }
        if connection is None:
            # Keep account authorization available during rolling deploys even if
            # the schema-default repair has not reached every API replica yet.
            connection = await self.connection_repo.create(
                id=uuid4(),
                bot_id=bot.id,
                **values,
            )
        else:
            updated = await self.connection_repo.update_by_bot_id(bot.id, **values)
            assert updated is not None
            connection = updated
        await self.db.commit()

        client = self._client(api_id=data.api_id, api_hash=api_hash, session="")
        try:
            await client.connect()
            sent_code = await client.send_code_request(phone_number)
            session = self._save_session(client)
        except Exception as exc:
            await self._persist_auth_error(bot.id, exc)
            raise self._auth_http_error(exc) from exc
        finally:
            await client.disconnect()

        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.TELEGRAM_ACCOUNT_AUTH_TTL_MINUTES
        )
        connection = await self.connection_repo.update_by_bot_id(
            bot.id,
            session_encrypted=self.credentials.encrypt(session),
            phone_code_hash_encrypted=self.credentials.encrypt(sent_code.phone_code_hash),
            auth_status="awaiting_code",
            connection_status="disconnected",
            auth_expires_at=expires_at,
            last_error=None,
        )
        await self._audit(
            bot_id=bot.id,
            actor=actor,
            action_type="telegram_account_code_requested",
            description="Запрошен код входа для рабочего Telegram-аккаунта.",
        )
        assert connection is not None
        return self._status_out(bot.id, connection)

    async def confirm_code(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        code: str,
        actor: User,
    ) -> TelegramAccountConnectionOut:
        bot = await self._get_account_bot(bot_id, project_id)
        connection = await self._pending_connection(bot.id, "awaiting_code")
        self._ensure_auth_not_expired(connection)
        api_hash, session, phone_code_hash = self._decrypt_login_state(connection)
        await self.db.commit()

        client = self._client(
            api_id=connection.api_id,
            api_hash=api_hash,
            session=session,
        )
        try:
            await client.connect()
            await client.sign_in(
                phone=connection.phone_number,
                code=self._normalize_code(code),
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            saved_session = self._save_session(client)
            updated = await self.connection_repo.update_by_bot_id(
                bot.id,
                session_encrypted=self.credentials.encrypt(saved_session),
                auth_status="awaiting_password",
                connection_status="disconnected",
                last_error=None,
            )
            await self.db.commit()
            assert updated is not None
            return self._status_out(bot.id, updated)
        except Exception as exc:
            await self._persist_auth_error(bot.id, exc, preserve_pending=True)
            raise self._auth_http_error(exc) from exc
        finally:
            await client.disconnect()

        return await self._finalize_authorization(
            bot=bot,
            connection=connection,
            client_session=self._save_session(client),
            actor=actor,
        )

    async def confirm_password(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        password: str,
        actor: User,
    ) -> TelegramAccountConnectionOut:
        bot = await self._get_account_bot(bot_id, project_id)
        connection = await self._pending_connection(bot.id, "awaiting_password")
        self._ensure_auth_not_expired(connection)
        api_hash = self.credentials.decrypt(
            connection.api_hash_encrypted,
            label="API hash",
        )
        session = self.credentials.decrypt(
            connection.session_encrypted,
            label="authorization session",
        )
        await self.db.commit()

        client = self._client(
            api_id=connection.api_id,
            api_hash=api_hash,
            session=session,
        )
        try:
            await client.connect()
            await client.sign_in(password=password)
            saved_session = self._save_session(client)
        except Exception as exc:
            await self._persist_auth_error(bot.id, exc, preserve_pending=True)
            raise self._auth_http_error(exc) from exc
        finally:
            await client.disconnect()

        return await self._finalize_authorization(
            bot=bot,
            connection=connection,
            client_session=saved_session,
            actor=actor,
        )

    async def sync_identity(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> TelegramAccountConnectionOut:
        bot = await self._get_account_bot(bot_id, project_id)
        connection = await self._authorized_connection(bot.id)
        api_hash = self.credentials.decrypt(connection.api_hash_encrypted, label="API hash")
        session = self.credentials.decrypt(
            connection.session_encrypted,
            label="authorization session",
        )
        await self.db.commit()

        client = self._client(connection.api_id, api_hash, session)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Telegram-сессия истекла. Подключите аккаунт заново.",
                )
            me = await client.get_me()
            saved_session = self._save_session(client)
        except HTTPException:
            raise
        except Exception as exc:
            await self._persist_auth_error(bot.id, exc, preserve_authorized=True)
            raise self._auth_http_error(exc) from exc
        finally:
            await client.disconnect()

        updated = await self._persist_identity(
            bot=bot,
            connection=connection,
            telegram_user=me,
            session=saved_session,
        )
        await self._audit(
            bot_id=bot.id,
            actor=actor,
            action_type="telegram_account_synced",
            description="Данные рабочего Telegram-аккаунта синхронизированы.",
        )
        return self._status_out(bot.id, updated)

    async def disconnect(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> None:
        bot = await self._get_account_bot(bot_id, project_id)
        connection = await self.connection_repo.get_by_bot_id(bot.id)
        if connection is None:
            return

        if connection.auth_status == "authorized" and connection.session_encrypted:
            api_hash = self.credentials.decrypt(connection.api_hash_encrypted, label="API hash")
            session = self.credentials.decrypt(
                connection.session_encrypted,
                label="authorization session",
            )
            await self.db.commit()
            client = self._client(connection.api_id, api_hash, session)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await client.log_out()
            except Exception as exc:
                raise self._auth_http_error(exc) from exc
            finally:
                await client.disconnect()

        await self.connection_repo.delete_by_bot_id(bot.id)
        await self._audit(
            bot_id=bot.id,
            actor=actor,
            action_type="telegram_account_disconnected",
            description="Рабочий Telegram-аккаунт отключён от CRM.",
        )

    async def _finalize_authorization(
        self,
        *,
        bot: Bot,
        connection: TelegramUserConnection,
        client_session: str,
        actor: User,
    ) -> TelegramAccountConnectionOut:
        api_hash = self.credentials.decrypt(connection.api_hash_encrypted, label="API hash")
        client = self._client(connection.api_id, api_hash, client_session)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Telegram не подтвердил авторизацию аккаунта.",
                )
            telegram_user = await client.get_me()
            if telegram_user is None or bool(getattr(telegram_user, "bot", False)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Нужен обычный рабочий Telegram-аккаунт, а не бот.",
                )
            saved_session = self._save_session(client)
        finally:
            await client.disconnect()

        updated = await self._persist_identity(
            bot=bot,
            connection=connection,
            telegram_user=telegram_user,
            session=saved_session,
        )
        await self._audit(
            bot_id=bot.id,
            actor=actor,
            action_type="telegram_account_connected",
            description="Рабочий Telegram-аккаунт подключён к CRM через MTProto.",
        )
        return self._status_out(bot.id, updated)

    async def _persist_identity(
        self,
        *,
        bot: Bot,
        connection: TelegramUserConnection,
        telegram_user: Any,
        session: str,
    ) -> TelegramUserConnection:
        now = datetime.now(timezone.utc)
        first_name = self._clean_optional(getattr(telegram_user, "first_name", None))
        last_name = self._clean_optional(getattr(telegram_user, "last_name", None))
        username = self._clean_optional(getattr(telegram_user, "username", None))
        telegram_user_id = int(getattr(telegram_user, "id"))
        updated = await self.connection_repo.update_by_bot_id(
            bot.id,
            session_encrypted=self.credentials.encrypt(session),
            phone_code_hash_encrypted=None,
            auth_status="authorized",
            connection_status="disconnected",
            telegram_user_id=telegram_user_id,
            telegram_first_name=first_name,
            telegram_last_name=last_name,
            telegram_username=username,
            auth_expires_at=None,
            last_synced_at=now,
            last_error=None,
        )
        await self.bot_repo.update_in_project(
            bot.id,
            bot.project_id,
            telegram_first_name=first_name,
            bot_username=username,
            telegram_bot_id=None,
            telegram_token=None,
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Этот Telegram-аккаунт уже подключён к другому объекту CRM.",
            ) from exc
        assert updated is not None
        return updated

    async def _persist_auth_error(
        self,
        bot_id: UUID,
        exc: Exception,
        *,
        preserve_pending: bool = False,
        preserve_authorized: bool = False,
    ) -> None:
        values: dict[str, Any] = {
            "connection_status": "error",
            "last_error": self._safe_error(exc),
        }
        if not preserve_pending and not preserve_authorized:
            values["auth_status"] = "error"
        await self.connection_repo.update_by_bot_id(bot_id, **values)
        await self.db.commit()

    async def _pending_connection(
        self,
        bot_id: UUID,
        expected_status: str,
    ) -> TelegramUserConnection:
        connection = await self.connection_repo.get_by_bot_id(bot_id, for_update=True)
        if connection is None or connection.auth_status != expected_status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Текущий этап подключения Telegram-аккаунта уже изменился. Начните вход заново.",
            )
        return connection

    async def _authorized_connection(self, bot_id: UUID) -> TelegramUserConnection:
        connection = await self.connection_repo.get_by_bot_id(bot_id)
        if connection is None or connection.auth_status != "authorized":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Telegram-аккаунт ещё не авторизован.",
            )
        return connection

    async def _get_account_bot(self, bot_id: UUID, project_id: UUID) -> Bot:
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        if bot.transport_type != "user_mtproto":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Для этого объекта выбран обычный Telegram Bot API.",
            )
        return bot

    async def _audit(
        self,
        *,
        bot_id: UUID,
        actor: User,
        action_type: str,
        description: str,
    ) -> None:
        await self.bot_repo.create_config_audit_log(
            bot_id=bot_id,
            user_id=actor.id,
            action_type=action_type,
            description=description,
        )

    def _decrypt_login_state(
        self,
        connection: TelegramUserConnection,
    ) -> tuple[str, str, str]:
        try:
            return (
                self.credentials.decrypt(connection.api_hash_encrypted, label="API hash"),
                self.credentials.decrypt(connection.session_encrypted, label="authorization session"),
                self.credentials.decrypt(
                    connection.phone_code_hash_encrypted,
                    label="phone code hash",
                ),
            )
        except TelegramAccountCredentialError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @staticmethod
    def _client(api_id: int, api_hash: str, session: str) -> TelegramClient:
        return TelegramClient(
            StringSession(session),
            api_id,
            api_hash,
            device_model="Sfera CRM",
            system_version="Server",
            app_version="1.0",
            sequential_updates=True,
            auto_reconnect=True,
        )

    @staticmethod
    def _save_session(client: TelegramClient) -> str:
        session = client.session
        if not isinstance(session, StringSession):
            raise RuntimeError("Telegram client did not use an encrypted string session")
        value = session.save()
        if not value:
            raise RuntimeError("Telegram did not return authorization session state")
        return value

    @staticmethod
    def _normalize_phone(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) < 7 or len(digits) > 15:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Укажите номер рабочего Telegram-аккаунта в международном формате.",
            )
        return f"+{digits}"

    @staticmethod
    def _normalize_code(value: str) -> str:
        code = re.sub(r"\s", "", value)
        if not code.isdigit():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Код Telegram должен содержать только цифры.",
            )
        return code

    @staticmethod
    def _ensure_auth_not_expired(connection: TelegramUserConnection) -> None:
        expires_at = connection.auth_expires_at
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Код входа истёк. Запросите новый код.",
            )

    @staticmethod
    def _clean_optional(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _mask_phone(value: str | None) -> str | None:
        if not value:
            return None
        digits = re.sub(r"\D", "", value)
        if len(digits) <= 4:
            return f"***{digits}"
        return f"+{digits[:2]}***{digits[-4:]}"

    @classmethod
    def _status_out(
        cls,
        bot_id: UUID,
        connection: TelegramUserConnection | None,
    ) -> TelegramAccountConnectionOut:
        if connection is None:
            return TelegramAccountConnectionOut(
                bot_id=bot_id,
                auth_status="disconnected",
                connection_status="disconnected",
            )
        return TelegramAccountConnectionOut(
            bot_id=bot_id,
            auth_status=connection.auth_status,
            connection_status=connection.connection_status,
            api_id=connection.api_id,
            api_hash_last_four=connection.api_hash_last_four,
            phone_number_masked=cls._mask_phone(connection.phone_number),
            telegram_user_id=connection.telegram_user_id,
            telegram_first_name=connection.telegram_first_name,
            telegram_last_name=connection.telegram_last_name,
            telegram_username=connection.telegram_username,
            auth_expires_at=connection.auth_expires_at,
            last_connected_at=connection.last_connected_at,
            last_synced_at=connection.last_synced_at,
            last_error=connection.last_error,
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, FloodWaitError):
            return f"Telegram временно ограничил вход. Повторите через {exc.seconds} сек."
        if isinstance(exc, PhoneNumberBannedError):
            return "Telegram заблокировал указанный номер."
        if isinstance(exc, (PhoneNumberInvalidError, PhoneNumberFloodError)):
            return "Telegram не принял номер телефона."
        if isinstance(exc, (ApiIdInvalidError, ApiIdPublishedFloodError)):
            return "Telegram не принял api_id/api_hash."
        if isinstance(exc, (PhoneCodeInvalidError, PhoneCodeExpiredError)):
            return "Telegram не принял код входа."
        if isinstance(exc, PasswordHashInvalidError):
            return "Неверный пароль двухэтапной аутентификации."
        return f"{exc.__class__.__name__}: {' '.join(str(exc).split())[:300]}"

    @classmethod
    def _auth_http_error(cls, exc: Exception) -> HTTPException:
        detail = cls._safe_error(exc)
        if isinstance(exc, FloodWaitError):
            return HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
                headers={"Retry-After": str(exc.seconds)},
            )
        if isinstance(
            exc,
            (
                ApiIdInvalidError,
                ApiIdPublishedFloodError,
                PhoneNumberInvalidError,
                PhoneNumberBannedError,
                PhoneNumberFloodError,
                PhoneCodeInvalidError,
                PhoneCodeExpiredError,
                PasswordHashInvalidError,
            ),
        ):
            return HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=detail,
            )
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось подключиться к Telegram: {detail}",
        )
