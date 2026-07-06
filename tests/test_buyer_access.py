from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.core.constants import RoleName
from app.services.buyer_bot_service import BuyerBotService, STATE_CREATE_LINK_BOT
from app.services.tracking_metrics_service import TrackingMetricsService
from app.services.tracking_service import TrackingService


class BuyerTrackingAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_buyer_link_list_is_scoped_to_actor(self) -> None:
        buyer_id = uuid4()
        project_id = uuid4()
        actor = SimpleNamespace(id=buyer_id, role_name=RoleName.BUYER)
        service = TrackingService.__new__(TrackingService)
        service.link_repo = SimpleNamespace(
            list_links=AsyncMock(return_value=[]),
            count_links=AsyncMock(return_value=0),
        )
        service._ensure_project_access = AsyncMock()
        service._get_active_project_or_404 = AsyncMock()

        items, total = await service.list_tracking_links(
            project_id=project_id,
            actor=actor,
            limit=50,
            offset=0,
        )

        self.assertEqual(items, [])
        self.assertEqual(total, 0)
        self.assertEqual(
            service.link_repo.list_links.await_args.kwargs["buyer_id"],
            buyer_id,
        )
        self.assertEqual(
            service.link_repo.count_links.await_args.kwargs["buyer_id"],
            buyer_id,
        )

    async def test_buyer_cannot_open_foreign_tracking_link(self) -> None:
        buyer_id = uuid4()
        project_id = uuid4()
        actor = SimpleNamespace(id=buyer_id, role_name=RoleName.BUYER)
        service = TrackingService.__new__(TrackingService)
        service.link_repo = SimpleNamespace(
            get_link_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid4(),
                    project_id=project_id,
                    buyer_id=uuid4(),
                )
            )
        )
        service._ensure_project_access = AsyncMock()
        service._get_active_project_or_404 = AsyncMock()

        with self.assertRaises(HTTPException) as raised:
            await service._get_link_for_actor(uuid4(), actor)

        self.assertEqual(raised.exception.status_code, 404)

    async def test_buyer_cannot_open_foreign_link_metrics(self) -> None:
        buyer_id = uuid4()
        project_id = uuid4()
        actor = SimpleNamespace(id=buyer_id, role_name=RoleName.BUYER)
        service = TrackingMetricsService.__new__(TrackingMetricsService)
        service.link_repo = SimpleNamespace(
            get_link_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid4(),
                    project_id=project_id,
                    buyer_id=uuid4(),
                )
            )
        )
        service._ensure_project_access = AsyncMock()

        with self.assertRaises(HTTPException) as raised:
            await service.get_link_metrics(actor, uuid4())

        self.assertEqual(raised.exception.status_code, 404)


class BuyerBotSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_project_bots_require_explicit_selection(self) -> None:
        project_id = uuid4()
        bots = [
            SimpleNamespace(id=uuid4(), name="Bot A", bot_username="bot_a"),
            SimpleNamespace(id=uuid4(), name="Bot B", bot_username="@bot_b"),
        ]
        service = BuyerBotService.__new__(BuyerBotService)
        service._list_client_bots = AsyncMock(return_value=bots)
        service._set_flow_state = AsyncMock()
        service._prompt_create_link_name = AsyncMock()
        service.telegram = SimpleNamespace(send_message=AsyncMock())

        await service._start_create_link(123, project_id)

        service._set_flow_state.assert_awaited_once_with(
            123,
            {"state": STATE_CREATE_LINK_BOT, "project_id": str(project_id)},
        )
        service._prompt_create_link_name.assert_not_awaited()
        markup = service.telegram.send_message.await_args.kwargs["reply_markup"]
        callbacks = [row[0]["callback_data"] for row in markup["inline_keyboard"][:-1]]
        self.assertEqual(callbacks, [f"create_bot:{bot.id}" for bot in bots])

    async def test_single_project_bot_is_selected_automatically(self) -> None:
        project_id = uuid4()
        bot = SimpleNamespace(id=uuid4(), name="Bot A", bot_username="bot_a")
        service = BuyerBotService.__new__(BuyerBotService)
        service._list_client_bots = AsyncMock(return_value=[bot])
        service._prompt_create_link_name = AsyncMock()
        service.telegram = SimpleNamespace(send_message=AsyncMock())

        await service._start_create_link(123, project_id)

        service._prompt_create_link_name.assert_awaited_once_with(123, project_id, bot)
        service.telegram.send_message.assert_not_awaited()

if __name__ == "__main__":
    unittest.main()
