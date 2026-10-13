"""Independent read-only info bot. Close database sessions before Telegram IO."""
import asyncio
import logging
import json
from uuid import uuid4
import httpx

from app.core.database import get_db_session
from app.services.admin_bot_service import AdminTelegramClient, AdminTelegramError
from app.services.info_bot_config import InfoBotConfigService
from app.services.info_bot_service import InfoBotService, InfoBotStateStore
from app.services.operational_alert_service import send_operational_alert
from app.repositories.info_bot_delivery_repository import InfoBotDeliveryRepository

logger = logging.getLogger(__name__)
OWNER_SCRIPT = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],90) else return 0 end"
RELEASE_SCRIPT = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
CHECKPOINT_SCRIPT = """
if redis.call('get',KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('set',KEYS[2],ARGV[2],'EX',86400)
return 1
"""
OFFSET_SCRIPT = """
if redis.call('get',KEYS[1]) ~= ARGV[1] then return 0 end
local current = tonumber(redis.call('get',KEYS[2]) or '0')
if tonumber(ARGV[2]) > current then redis.call('set',KEYS[2],ARGV[2]) end
return 1
"""


async def _checkpoint(redis, lock_key, owner, delivery_key, plan):
    if not await redis.eval(OWNER_SCRIPT, 1, lock_key, owner):
        raise RuntimeError("Info bot polling ownership lost")
    bot_id, update_id = lock_key.rsplit(":", 1)[-1], int(delivery_key.rsplit(":", 1)[-1])
    async with get_db_session() as db:
        await InfoBotDeliveryRepository(db).save_plan(bot_id, update_id, plan)
        await db.commit()
    if not await redis.eval(CHECKPOINT_SCRIPT, 2, lock_key, delivery_key, owner, json.dumps(plan)):
        raise RuntimeError("Info bot polling ownership lost")


async def _heartbeat(redis, lock_key, owner):
    try:
        while True:
            await asyncio.sleep(20)
            if not await redis.eval(OWNER_SCRIPT, 1, lock_key, owner):
                return
    except Exception as exc:
        logger.error("Info bot polling heartbeat failed: %s", type(exc).__name__)


class InfoTelegramClient(AdminTelegramClient):
    async def send_message(self, chat_id, text, *, reply_markup=None):
        payload = {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        data = await self._post("sendMessage", payload)
        return (data.get("result") or {}).get("message_id")

    async def set_commands(self):
        await self._post("setMyCommands", {"commands": [
            {"command": "stats", "description": "Проекты и статистика"},
            {"command": "cancel", "description": "Вернуться к проектам"},
        ]})


async def run_loop():
    state = InfoBotStateStore()
    owner = str(uuid4())
    client, current_token, lock_key = None, None, None
    heartbeat = None
    try:
        while True:
            try:
                async with get_db_session() as db:
                    token = await InfoBotConfigService(db).token()
                if token != current_token:
                    if heartbeat:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
                        heartbeat = None
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
                    if heartbeat:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
                    heartbeat = asyncio.create_task(_heartbeat(state.redis, lock_key, owner))
                    await client.set_commands()
                if heartbeat is None or heartbeat.done():
                    heartbeat = asyncio.create_task(_heartbeat(state.redis, lock_key, owner))
                offset_key = lock_key + ":offset"
                offset = await state.redis.get(offset_key)
                async with get_db_session() as db:
                    stored_offset = await InfoBotDeliveryRepository(db).offset(client.bot_id)
                if stored_offset is not None:
                    offset = max(int(offset or 0), stored_offset)
                updates = await client.get_updates(offset=int(offset) if offset else None, timeout_seconds=25)
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int) and offset is not None and update_id < int(offset):
                        continue
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
                    async with get_db_session() as db:
                        plan = await InfoBotDeliveryRepository(db).plan(client.bot_id, update_id)
                    if plan is None and cached:
                        plan = json.loads(cached)  # Adopt pre-upgrade Redis checkpoints.
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
                                    await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
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
                        await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
                        logger.info("Info bot response prepared update_id=%s chat_id=%s replies=%s",
                                    update.get("update_id"), chat_id, len(replies))
                    # Reports are materialized: no ORM access or transaction during sending.
                    for index in range(plan["sent"], len(replies)):
                        if not await state.redis.eval(OWNER_SCRIPT, 1, lock_key, owner):
                            raise RuntimeError("Polling ownership expired")
                        if plan.get("inflight") == index:
                            # Telegram has no sendMessage idempotency key. A timeout
                            # or crash may follow a successful send; never resend blindly.
                            plan["sent"] = index + 1
                            plan.pop("inflight", None)
                            await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
                            logger.warning("Info bot delivery uncertain; duplicate suppressed update_id=%s reply=%s", update_id, index)
                            await send_operational_alert(component="info_bot", title="Report delivery uncertain; automatic resend suppressed",
                                details={"update_id": update_id, "reply_index": index, "action": "Request the report again if it did not arrive"},
                                dedupe_key=f"info-bot-uncertain:{lock_key}:{update_id}:{index}")
                            continue
                        plan["inflight"] = index
                        plan["attempt_id"] = str(uuid4())
                        await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
                        try:
                            telegram_message_id = await client.send_message(chat_id, **replies[index])
                            logger.info("Info bot Telegram send confirmed update_id=%s reply=%s telegram_message_id=%s attempt_id=%s",
                                        update_id, index, telegram_message_id, plan["attempt_id"])
                        except AdminTelegramError as exc:
                            if exc.code is not None and exc.code < 500:
                                plan.pop("inflight", None)
                                await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
                            if not exc.recipient_unavailable:
                                raise
                            logger.warning("Info bot recipient unavailable update_id=%s chat_id=%s telegram_code=%s",
                                           update.get("update_id"), chat_id, exc.code)
                            break
                        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                            plan.pop("inflight", None)
                            await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
                            raise
                        plan["sent"] = index + 1
                        plan.setdefault("message_ids", {})[str(index)] = telegram_message_id
                        plan.pop("inflight", None)
                        await _checkpoint(state.redis, lock_key, owner, delivery_key, plan)
                        logger.info("Info bot response delivered update_id=%s reply=%s/%s",
                                    update.get("update_id"), index + 1, len(replies))
                        await asyncio.sleep(0.05)
                    if isinstance(update.get("update_id"), int):
                        offset = update["update_id"] + 1
                        if not await state.redis.eval(OFFSET_SCRIPT, 2, lock_key, offset_key, owner, offset):
                            raise RuntimeError("Info bot polling ownership lost before acknowledgement")
                        async with get_db_session() as db:
                            await InfoBotDeliveryRepository(db).save_offset(client.bot_id, offset)
                            await db.commit()
                        await state.redis.delete(failure_key)
                async with get_db_session() as db:
                    await InfoBotDeliveryRepository(db).cleanup(client.bot_id)
                    await db.commit()
            except Exception as exc:
                # HTTP exception strings can contain token-bearing Telegram URLs.
                logger.error("Info bot cycle failed: %s", type(exc).__name__)
                await asyncio.sleep(5)
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if client:
            await client.close()
        if lock_key:
            await state.redis.eval(RELEASE_SCRIPT, 1, lock_key, owner)
        await state.close()
