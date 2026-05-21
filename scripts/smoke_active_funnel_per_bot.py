"""Service-level smoke for one active published funnel per bot.

Usage:
  python scripts/smoke_active_funnel_per_bot.py \
    --project-id <uuid> \
    --bot-id <uuid> \
    --actor-id <crm-user-id>

This creates two small smoke funnels for the same bot, publishes the first,
then publishes the second. It verifies that the bot active pointers end on the
second version and the first published version is archived.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import UUID

from app.core.database import get_db_session
from app.repositories.bot_repository import BotRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.user_repository import UserRepository
from app.schemas.funnel import FunnelCreate
from app.services.funnel_service import FunnelService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--actor-id", required=True)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    project_id = UUID(args.project_id)
    bot_id = UUID(args.bot_id)
    actor_id = UUID(args.actor_id)

    async with get_db_session() as db:
        actor = await UserRepository(db).get_by_id(actor_id)
        if actor is None:
            raise SystemExit(f"Actor not found: {actor_id}")

        bot = await BotRepository(db).get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise SystemExit(f"Bot not found in project: {bot_id}")

        service = FunnelService(db)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        first = await service.create_funnel(
            project_id=project_id,
            data=FunnelCreate(
                project_id=project_id,
                bot_id=bot_id,
                name=f"Smoke active funnel A {stamp}",
            ),
            current_user=actor,
        )
        if first.draft_version_id is None:
            raise SystemExit("First smoke funnel did not get a draft version")
        first_version = await service.publish_version(
            funnel_id=first.id,
            version_id=first.draft_version_id,
            project_id=project_id,
            current_user=actor,
        )

        second = await service.create_funnel(
            project_id=project_id,
            data=FunnelCreate(
                project_id=project_id,
                bot_id=bot_id,
                name=f"Smoke active funnel B {stamp}",
            ),
            current_user=actor,
        )
        if second.draft_version_id is None:
            raise SystemExit("Second smoke funnel did not get a draft version")
        second_version = await service.publish_version(
            funnel_id=second.id,
            version_id=second.draft_version_id,
            project_id=project_id,
            current_user=actor,
        )

        await db.commit()

        refreshed_bot = await BotRepository(db).get_by_id_in_project(bot_id, project_id)
        if refreshed_bot is None:
            raise SystemExit("Bot disappeared after publish smoke")
        if refreshed_bot.active_funnel_id != second.id:
            raise SystemExit("Bot active_funnel_id does not point to the second funnel")
        if refreshed_bot.active_funnel_version_id != second_version.id:
            raise SystemExit(
                "Bot active_funnel_version_id does not point to the second version"
            )

        repo = FunnelRepository(db)
        archived_first = await repo.get_version(first_version.id)
        if archived_first is None or archived_first.status != "archived":
            raise SystemExit("First published version was not archived")

        _, active_version = await repo.get_active_funnel_for_bot(bot_id, project_id)
        if active_version is None or active_version.id != second_version.id:
            raise SystemExit("Repository active funnel lookup did not return the second version")

        print(
            "ok active_funnel_per_bot "
            f"bot_id={bot_id} active_version_id={second_version.id}"
        )


if __name__ == "__main__":
    asyncio.run(main())
