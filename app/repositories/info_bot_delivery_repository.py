from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from app.models.info_bot_delivery import InfoBotCursor, InfoBotDelivery


class InfoBotDeliveryRepository:
    def __init__(self, db):
        self.db = db

    async def plan(self, bot_id, update_id):
        return await self.db.scalar(select(InfoBotDelivery.plan_json).where(
            InfoBotDelivery.bot_id == bot_id, InfoBotDelivery.update_id == update_id))

    async def save_plan(self, bot_id, update_id, plan):
        sent = InfoBotDelivery.plan_json["sent"].as_integer()
        guard = func.coalesce(sent, 0) <= plan["sent"]
        if plan.get("inflight") is not None:
            guard = guard & (InfoBotDelivery.plan_json["inflight"].as_integer().is_(None)
                | (InfoBotDelivery.plan_json["attempt_id"].as_string() == plan["attempt_id"]))
        result = await self.db.execute(insert(InfoBotDelivery).values(
            bot_id=bot_id, update_id=update_id, plan_json=plan).on_conflict_do_update(
                index_elements=[InfoBotDelivery.bot_id, InfoBotDelivery.update_id],
                set_={"plan_json": plan, "updated_at": func.now()}, where=guard).returning(InfoBotDelivery.update_id))
        if result.scalar_one_or_none() is None:
            raise RuntimeError("Info bot delivery checkpoint superseded")

    async def offset(self, bot_id):
        return await self.db.scalar(select(InfoBotCursor.next_update_id).where(InfoBotCursor.bot_id == bot_id))

    async def save_offset(self, bot_id, offset):
        await self.db.execute(insert(InfoBotCursor).values(bot_id=bot_id, next_update_id=offset)
            .on_conflict_do_update(index_elements=[InfoBotCursor.bot_id],
                set_={"next_update_id": func.greatest(InfoBotCursor.next_update_id, offset), "updated_at": func.now()}))

    async def cleanup(self, bot_id):
        await self.db.execute(delete(InfoBotDelivery).where(InfoBotDelivery.bot_id == bot_id,
            InfoBotDelivery.created_at < datetime.now(timezone.utc) - timedelta(days=7)))
