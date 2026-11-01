"""Separate super-admin bot for shared slot editing; never sends posts to leads."""
import json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select

from app.models.advertising import AdvertisingConfig, AdvertisingSlot
from app.models.project import Project
from app.schemas.advertising import SlotWrite
from app.services.advertising_service import AdvertisingService
from app.services.info_bot_service import InfoBotService, InfoBotStateStore, keyboard
from app.services.info_bot_config import InfoBotConfigService

AD_BOT_KEY = "advertising_bot_config_v1"


class AdvertisingBotConfig(InfoBotConfigService):
    async def read(self):
        return json.loads(await self.settings.get_value(AD_BOT_KEY) or "{}")


class AdvertisingBotState(InfoBotStateStore):
    @staticmethod
    def _key(chat_id):
        return f"advertising_bot:fsm:{chat_id}"


class AdvertisingBotService(InfoBotService):
    async def handle_update(self, update):
        callback = update.get("callback_query") or {}
        message = callback.get("message") or update.get("message") or {}
        chat = message.get("chat") or {}
        sender = callback.get("from") or message.get("from") or {}
        chat_id = chat.get("id")
        if chat.get("type") != "private" or sender.get("id") != chat_id or not isinstance(chat_id, int):
            return None, []
        actor = await self.authorized_user(chat_id)
        if actor is None:
            return chat_id, [{"text": "Доступ только суперадминистраторам с привязанным Telegram ID."}]
        state = await self.state_store.get(chat_id) or {}
        data = str(callback.get("data") or "")
        body = str(message.get("text") or "").strip() if not callback else ""
        try:
            if body in {"/start", "/stats", "/cancel"} or data == "ad:projects":
                await self.state_store.clear(chat_id)
                projects = (await self.db.execute(select(Project.id, Project.name).join(AdvertisingConfig,
                    AdvertisingConfig.project_id == Project.id).where(AdvertisingConfig.enabled.is_(True), Project.is_deleted.is_(False)).distinct()
                    .order_by(Project.name).limit(50))).all()
                return chat_id, [{"text": "Рекламные сценарии", "reply_markup": keyboard([[(name, f"ad:project:{pid}")] for pid, name in projects])}]
            if data.startswith("ad:project:"):
                pid = UUID(data.split(":")[-1])
                scenarios = [r for r in await AdvertisingService(self.db).scenarios(pid) if r.enabled]
                return chat_id, [{"text": "Выберите сценарий", "reply_markup": keyboard(
                    [[(s.name, f"ad:scenario:{s.id}")] for s in scenarios] + [[("Проекты", "ad:projects")]])}]
            if data.startswith("ad:scenario:"):
                scenario = await self.db.get(AdvertisingConfig, UUID(data.split(":")[-1]))
                if not scenario or not scenario.enabled:
                    raise ValueError("Сценарий отключён")
                slots = (await self.db.scalars(select(AdvertisingSlot).where(AdvertisingSlot.scenario_id == scenario.id)
                    .order_by(AdvertisingSlot.position, AdvertisingSlot.id).limit(80))).all()
                return chat_id, [{"text": f"Слоты: {scenario.name}", "reply_markup": keyboard(
                    [[(f"{i + 1}. {s.name}", f"ad:slot:{s.id}")] for i, s in enumerate(slots)] + [[("Проекты", "ad:projects")]])}]
            if data.startswith("ad:slot:"):
                slot = await self.db.get(AdvertisingSlot, UUID(data.split(":")[-1]))
                if slot is None or not (await AdvertisingService(self.db, slot.scenario_id).config(slot.project_id)).enabled:
                    raise ValueError("Слот недоступен")
                draft = SlotWrite(name=slot.name, position=slot.position, enabled=slot.enabled,
                    delay_minutes=slot.delay_minutes, revision=slot.revision, content_json=slot.content_json).model_dump(mode="json")
                state = {"slot_id": str(slot.id), "project_id": str(slot.project_id), "scenario_id": str(slot.scenario_id), "draft": draft}
                await self.state_store.set(chat_id, state)
                return chat_id, self.menu(state)
            if not state.get("draft"):
                raise ValueError("Выберите слот через /start")
            if data.startswith("ad:edit:"):
                field = data.split(":")[-1]
                prompts = {"text": "Пришлите новый текст (Telegram HTML). Для медиа это подпись.",
                    "delay": "Пришлите интервал перед слотом в минутах (1–43200). Первый слот отправляется сразу.",
                    "buttons": "Пришлите кнопки: каждая строка Название | https://адрес. Минус (-) удаляет кнопки.",
                    "media": "Пришлите фото, видео, голосовое, кружок или документ (до 20 МБ)."}
                if field not in prompts:
                    raise ValueError("Неизвестное действие")
                state["editing"] = field
                await self.state_store.set(chat_id, state)
                return chat_id, [{"text": prompts[field]}]
            if data == "ad:toggle":
                state["draft"]["enabled"] = not state["draft"]["enabled"]
            elif data == "ad:save":
                slot = await AdvertisingService(self.db, UUID(state.get("scenario_id") or state["project_id"])).save_slot(UUID(state["project_id"]),
                    SlotWrite.model_validate(state["draft"]), actor.id, UUID(state["slot_id"]))
                state["draft"]["revision"] = slot.revision
                await self.state_store.set(chat_id, state)
                return chat_id, [{"text": "Сохранено. Отправленные посты и состав существующих очередей не изменены."}, *self.menu(state)]
            elif state.get("editing") == "media" and not callback and any(message.get(k) for k in ("photo", "video", "voice", "video_note", "document")):
                upload = await self.upload_media(message, actor, UUID(state["project_id"]))
                message_draft = state["draft"]["content_json"]["messages"][0]
                message_draft.update(type=upload.media_type,
                    media={"source": "upload", "upload_id": str(upload.upload_id), "file_name": upload.file_name},
                    caption=message_draft.get("caption") or message_draft.get("text") or "")
                state.pop("editing", None)
            elif body and state.get("editing"):
                field = state.pop("editing")
                message_draft = state["draft"]["content_json"]["messages"][0]
                if field == "text":
                    message_draft["text" if message_draft.get("type", "text") == "text" else "caption"] = body
                    message_draft["parse_mode"] = "HTML"
                elif field == "delay":
                    state["draft"]["delay_minutes"] = int(body)
                elif field == "buttons":
                    buttons = []
                    if body != "-":
                        for line in body.splitlines():
                            label, url = line.split("|", 1)
                            buttons.append({"label": label.strip(), "url": url.strip(), "type": "url"})
                    message_draft["buttons"] = buttons
                elif field == "media":
                    from app.models.broadcast import BroadcastUpload
                    upload = await self.db.get(BroadcastUpload, UUID(body))
                    if not upload or str(upload.project_id) != state["project_id"]:
                        raise ValueError("Медиа не найдено в этом проекте")
                    message_draft.update(type=upload.media_type, media={"source": "upload", "upload_id": str(upload.id)},
                        caption=message_draft.get("caption") or message_draft.get("text") or "")
            await self.state_store.set(chat_id, state)
            return chat_id, self.menu(state)
        except (ValueError, HTTPException) as exc:
            return chat_id, [{"text": str(getattr(exc, "detail", str(exc)))[:3000]}]

    @staticmethod
    def menu(state):
        draft = state["draft"]
        message = draft["content_json"]["messages"][0]
        preview = str(message.get("caption") or message.get("text") or "")
        buttons = "\n".join(f"{b.get('label', '')}: {b.get('url', '')}" for b in message.get("buttons", []))
        return [{"text": f"{draft['name']} · версия {draft['revision']}\nИнтервал: {draft['delay_minutes']} мин.\n"
            f"Активен: {'да' if draft['enabled'] else 'нет'}\nТип: {message.get('type', 'text')}\n\n{preview[:2300]}\n{buttons[:600]}",
            "reply_markup": keyboard([[('Текст', 'ad:edit:text'), ('Медиа', 'ad:edit:media')],
                [('Кнопки', 'ad:edit:buttons'), ('Интервал', 'ad:edit:delay')],
                [('Включить / выключить', 'ad:toggle')], [('Сохранить изменения', 'ad:save')], [('Проекты', 'ad:projects')]])}]

    async def upload_media(self, message, actor, project_id):
        import io
        import httpx
        from starlette.datastructures import UploadFile, Headers
        from app.services.admin_bot_service import AdminTelegramClient
        from app.services.broadcast_service import BroadcastService
        media_type = next(k for k in ("photo", "video", "voice", "video_note", "document") if message.get(k))
        info = message[media_type][-1] if media_type == "photo" else message[media_type]
        limit = 20 * 1024 * 1024
        if int(info.get("file_size") or 0) > limit:
            raise ValueError("Файл больше 20 МБ. Загрузите его через CRM")
        token = await AdvertisingBotConfig(self.db).token()
        if not token:
            raise ValueError("Рекламный бот отключён")
        client = AdminTelegramClient(token)
        try:
            result = await client._post("getFile", {"file_id": info["file_id"]})
            path = str((result.get("result") or {}).get("file_path") or "")
            if not path or path.startswith("/") or ".." in path or ":" in path:
                raise ValueError("Telegram не вернул файл")
            buffer = io.BytesIO()
            async with httpx.AsyncClient(timeout=30) as http:
                async with http.stream("GET", f"https://api.telegram.org/file/bot{token}/{path}") as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        if buffer.tell() + len(chunk) > limit:
                            raise ValueError("Файл больше 20 МБ")
                        buffer.write(chunk)
            buffer.seek(0)
            mime = info.get("mime_type") or {"photo": "image/jpeg", "video": "video/mp4", "video_note": "video/mp4", "voice": "audio/ogg"}.get(media_type, "application/octet-stream")
            upload = UploadFile(buffer, filename=info.get("file_name") or path.rsplit("/", 1)[-1], headers=Headers({"content-type": mime}))
            try:
                return await BroadcastService(self.db).upload_media(actor=actor, project_id=project_id, file=upload, media_type=media_type)
            finally:
                await upload.close()
        except httpx.HTTPError:
            raise ValueError("Не удалось загрузить файл из Telegram. Попробуйте ещё раз") from None
        finally:
            await client.close()
