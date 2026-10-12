"""Independent read-only info bot. Close database sessions before Telegram IO."""
import asyncio
import logging
import json
from uuid import uuid4

from app.core.database import get_db_session
from app.services.admin_bot_service import AdminTelegramClient, AdminTelegramError
from app.services.info_bot_config import InfoBotConfigService
from app.services.info_bot_service import InfoBotService, InfoBotStateStore

logger = logging.getLogger(__name__)
OWNER_SCRIPT = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],90) else return 0 end"
RELEASE_SCRIPT = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


class InfoTelegramClient(AdminTelegramClient):
    async def set_commands(self):
        await self._post("setMyCommands", {"commands": [
            {"command": "stats", "description": "Проекты и статистика"},
            {"command": "cancel", "description": "Вернуться к проектам"},
        ]})


async def run_loop():
    state = InfoBotStateStore()
    owner = str(uuid4())
    client, current_token, lock_key = None, None, None
    try:
        while True:
            try:
                async with get_db_session() as db:
                    token = await InfoBotConfigService(db).token()
                if token != current_token:
                    if client:
                        await client.close()
                    if lock_key:
                        await state.redis.eval(RELEASE_SCRIPT, 1, lock_key, owner)
                    current_token = token
                    client = InfoTelegramClient(token) if token else None
                    lock_key = f"info_bot:poller:{token.split(':')[0]}" if token else None
                if not client:
                    await asyncio.sleep(25)
                    continue
                owns_lock = await state.redis.eval(OWNER_SCRIPT, 1, lock_key, owner)
                if not owns_lock:
                    if not await state.redis.set(lock_key, owner, nx=True, ex=90):
                        await asyncio.sleep(10)
                        continue
                    await client.set_commands()
                offset_key = lock_key + ":offset"
                offset = await state.redis.get(offset_key)
                updates = await client.get_updates(offset=int(offset) if offset else None, timeout_seconds=25)
                for update in updates:
                    if not await state.redis.eval(OWNER_SCRIPT, 1, lock_key, owner):
                        break
                    callback_id = (update.get("callback_query") or {}).get("id")
                    if callback_id:
                        await client.answer_callback_query(callback_id)
                    if not await state.redis.eval(OWNER_SCRIPT, 1, lock_key, owner):
                        break
                    failure_key = f"{lock_key}:failure:{update.get('update_id')}"
                    delivery_key = f"{lock_key}:delivery:{update.get('update_id')}"
                    cached = await state.redis.get(delivery_key)
                    plan = json.loads(cached) if cached else None
                    try:
                        if plan is not None:
                            chat_id, replies = plan["chat_id"], plan["replies"]
                            # Cached delivery must not outlive a revoked CRM role.
                            if chat_id is not None:
                                async with get_db_session() as db:
                                    authorized = await InfoBotService(db, state).authorized_user(chat_id)
                                    allowed = authorized is not None
                                if not allowed:
                                    replies = [{"text": "Доступ только для суперадминистраторов CRM с привязанным Telegram ID."}]
                                    plan = {"chat_id": chat_id, "replies": replies, "sent": 0}
                                    await state.clear(chat_id)
                                    await state.redis.set(delivery_key, json.dumps(plan), ex=86400)
                        else:
                            async with asyncio.timeout(60):
                                async with get_db_session() as db:
                                    chat_id, replies = await InfoBotService(db, state).handle_update(update)
                                    await db.rollback()
                    except Exception as exc:
                        failures = await state.redis.incr(failure_key)
                        await state.redis.expire(failure_key, 300)
                        logger.error("Info bot report failed update_id=%s attempt=%s error=%s",
                                     update.get("update_id"), failures, type(exc).__name__)
                        if failures < 3:
                            raise
                        message = (update.get("callback_query") or {}).get("message") or update.get("message") or {}
                        chat = message.get("chat") or {}
                        chat_id = chat.get("id") if chat.get("type") == "private" else None
                        replies = [{"text": "Не удалось рассчитать отчёт. Повторите запрос через /stats."}] if chat_id else []
                    if plan is None:
                        plan = {"chat_id": chat_id, "replies": replies, "sent": 0}
                        await state.redis.set(delivery_key, json.dumps(plan), ex=86400)
                        logger.info("Info bot response prepared update_id=%s chat_id=%s replies=%s",
                                    update.get("update_id"), chat_id, len(replies))
                    # Reports are materialized: no ORM access or transaction during sending.
                    for index in range(plan["sent"], len(replies)):
                        if not await state.redis.eval(OWNER_SCRIPT, 1, lock_key, owner):
                            raise RuntimeError("Polling ownership expired")
                        try:
                            await client.send_message(chat_id, **replies[index])
                        except AdminTelegramError as exc:
                            if not exc.recipient_unavailable:
                                raise
                            logger.warning("Info bot recipient unavailable update_id=%s chat_id=%s telegram_code=%s",
                                           update.get("update_id"), chat_id, exc.code)
                            break
                        plan["sent"] = index + 1
                        await state.redis.set(delivery_key, json.dumps(plan), ex=86400)
                        logger.info("Info bot response delivered update_id=%s reply=%s/%s",
                                    update.get("update_id"), index + 1, len(replies))
                        await asyncio.sleep(0.05)
                    if isinstance(update.get("update_id"), int):
                        await state.redis.set(offset_key, update["update_id"] + 1)
                        await state.redis.delete(failure_key)
                        await state.redis.delete(delivery_key)
            except Exception as exc:
                # HTTP exception strings can contain token-bearing Telegram URLs.
                logger.error("Info bot cycle failed: %s", type(exc).__name__)
                await asyncio.sleep(5)
    finally:
        if client:
            await client.close()
        if lock_key:
            await state.redis.eval(RELEASE_SCRIPT, 1, lock_key, owner)
        await state.close()
