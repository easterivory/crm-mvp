from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1.routers.messages import (
    _ensure_message_translation_access,
    _ensure_message_write_access,
)
from app.core.constants import RoleName
from app.schemas.lander import ProjectLanderCreate
from app.services.buyer_bot_service import BuyerBotService, STATE_CREATE_LINK_BOT
from app.services.funnel_service import FunnelService
from app.services.lander_admin_service import LanderAdminService
from app.services.tracking_metrics_service import TrackingMetricsService
from app.services.tracking_service import TrackingService


class BuyerMessageTranslationAccessTests(unittest.TestCase):
    def test_buyer_can_translate_existing_message_but_cannot_send(self) -> None:
        buyer = SimpleNamespace(role_name=RoleName.BUYER)

        _ensure_message_translation_access(buyer)

        with self.assertRaises(HTTPException) as raised:
            _ensure_message_write_access(buyer)
        self.assertEqual(raised.exception.status_code, 403)

    def test_unknown_role_cannot_translate_messages(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _ensure_message_translation_access(SimpleNamespace(role_name="unknown"))

        self.assertEqual(raised.exception.status_code, 403)


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


class BuyerFunnelSelfRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_funnel_is_restarted_in_buyers_own_telegram_chat(self) -> None:
        buyer_id = uuid4()
        project_id = uuid4()
        funnel_id = uuid4()
        version_id = uuid4()
        bot_id = uuid4()
        chat_id = uuid4()
        actor = SimpleNamespace(
            id=buyer_id,
            role_name=RoleName.BUYER,
            buyer_telegram_id=123456789,
        )
        funnel = SimpleNamespace(
            id=funnel_id,
            project_id=project_id,
            bot_id=bot_id,
            status="active",
        )
        version = SimpleNamespace(id=version_id, version_number=7)
        chat = SimpleNamespace(
            id=chat_id,
            is_blocked=False,
            is_blocked_by_user=False,
        )
        runtime = SimpleNamespace(
            lock_chat_for_runtime=AsyncMock(return_value=True),
            reset_chat_state=AsyncMock(),
            start_funnel_for_chat=AsyncMock(
                return_value=SimpleNamespace(id=uuid4(), step_type="trigger")
            ),
        )
        service = FunnelService.__new__(FunnelService)
        service.db = SimpleNamespace()
        service.repo = SimpleNamespace(
            get_current_published_version=AsyncMock(return_value=version),
            list_steps=AsyncMock(
                return_value=[SimpleNamespace(id=uuid4(), step_type="trigger")]
            ),
        )
        service.chat_repo = SimpleNamespace(
            get_active_by_telegram_identity=AsyncMock(return_value=chat)
        )
        service.bot_repo = SimpleNamespace(reset_chat_state=AsyncMock())
        service.audit = SimpleNamespace(log=AsyncMock())
        service._get_funnel_or_404 = AsyncMock(return_value=funnel)

        with patch(
            "app.services.funnel_service.FunnelRuntimeService",
            return_value=runtime,
        ):
            result = await service.restart_funnel_for_buyer_self(
                funnel_id=funnel_id,
                project_id=project_id,
                current_user=actor,
            )

        self.assertEqual(result.funnel_id, funnel_id)
        self.assertEqual(result.funnel_version_id, version_id)
        self.assertEqual(result.chat_id, chat_id)
        service.chat_repo.get_active_by_telegram_identity.assert_awaited_once_with(
            project_id=project_id,
            bot_id=bot_id,
            telegram_id=123456789,
        )
        runtime.start_funnel_for_chat.assert_awaited_once_with(
            chat_id=chat_id,
            funnel_id=funnel_id,
            funnel_version_id=version_id,
        )

    async def test_unlinked_buyer_cannot_restart_funnel(self) -> None:
        service = FunnelService.__new__(FunnelService)
        actor = SimpleNamespace(
            id=uuid4(),
            role_name=RoleName.BUYER,
            buyer_telegram_id=None,
        )

        with self.assertRaises(HTTPException) as raised:
            await service.restart_funnel_for_buyer_self(
                funnel_id=uuid4(),
                project_id=uuid4(),
                current_user=actor,
            )

        self.assertEqual(raised.exception.status_code, 422)

    async def test_buyer_cannot_choose_a_chat_id_for_self_restart(self) -> None:
        buyer_telegram_id = 987654321
        service = FunnelService.__new__(FunnelService)
        service.db = SimpleNamespace()
        service.repo = SimpleNamespace(
            get_current_published_version=AsyncMock(
                return_value=SimpleNamespace(id=uuid4(), version_number=1)
            ),
            list_steps=AsyncMock(
                return_value=[SimpleNamespace(id=uuid4(), step_type="trigger")]
            ),
        )
        service.chat_repo = SimpleNamespace(
            get_active_by_telegram_identity=AsyncMock(return_value=None)
        )
        service._get_funnel_or_404 = AsyncMock(
            return_value=SimpleNamespace(
                id=uuid4(),
                bot_id=uuid4(),
                status="active",
            )
        )
        actor = SimpleNamespace(
            id=uuid4(),
            role_name=RoleName.BUYER,
            buyer_telegram_id=buyer_telegram_id,
        )

        with self.assertRaises(HTTPException) as raised:
            await service.restart_funnel_for_buyer_self(
                funnel_id=uuid4(),
                project_id=uuid4(),
                current_user=actor,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            service.chat_repo.get_active_by_telegram_identity.await_args.kwargs[
                "telegram_id"
            ],
            buyer_telegram_id,
        )


class BuyerFacebookCampaignAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_buyer_campaign_uses_pixel_credentials_from_buyer_bot(self) -> None:
        project_id = uuid4()
        bot_id = uuid4()
        actor = SimpleNamespace(
            id=uuid4(),
            name="Buyer One",
            role_name=RoleName.BUYER,
            buyer_fb_pixel_id="123456789012345",
            buyer_fb_capi_token="buyer-capi-token",
        )
        data = ProjectLanderCreate.model_validate(
            {
                "name": "Campaign One",
                "type": "default_tg_redirect",
                "slug": "campaign-one",
                "campaign": {
                    "bot_id": bot_id,
                    "title": "Campaign One",
                },
            }
        )
        created_link = SimpleNamespace(
            id=uuid4(),
            code="campaign-code",
            fb_pixel_id=actor.buyer_fb_pixel_id,
        )
        tracking_service = SimpleNamespace(
            create_tracking_link=AsyncMock(return_value=created_link)
        )
        service = LanderAdminService.__new__(LanderAdminService)
        service.db = SimpleNamespace(add=Mock(), flush=AsyncMock())
        service._ensure_lander_project_access = AsyncMock()
        service._slug_exists = AsyncMock(return_value=False)
        service._technical_domain = Mock(return_value="lp.sfera.cyou")
        service._get_lander = AsyncMock(return_value=SimpleNamespace())
        service._to_lander_out = Mock(return_value="created")

        with patch(
            "app.services.lander_admin_service.TrackingService",
            return_value=tracking_service,
        ):
            result = await service.create_lander(
                project_id=project_id,
                data=data,
                actor=actor,
            )

        self.assertEqual(result, "created")
        tracking_data = tracking_service.create_tracking_link.await_args.kwargs["data"]
        self.assertEqual(tracking_data.fb_pixel_id, actor.buyer_fb_pixel_id)
        self.assertEqual(tracking_data.fb_capi_token, actor.buyer_fb_capi_token)
        self.assertTrue(tracking_data.fb_campaign_enabled)

    async def test_buyer_campaign_list_is_scoped_to_own_tracking_links(self) -> None:
        buyer_id = uuid4()
        project_id = uuid4()
        query_result = SimpleNamespace(
            scalars=Mock(return_value=SimpleNamespace(all=Mock(return_value=[])))
        )
        db = SimpleNamespace(execute=AsyncMock(return_value=query_result))
        service = LanderAdminService(db)
        service._ensure_lander_project_access = AsyncMock()

        items = await service.list_landers(
            project_id=project_id,
            actor=SimpleNamespace(id=buyer_id, role_name=RoleName.BUYER),
        )

        self.assertEqual(items, [])
        statement = db.execute.await_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertIn("JOIN tracking_links", str(compiled))
        self.assertIn("tracking_links.buyer_id", str(compiled))
        self.assertIn(buyer_id, compiled.params.values())

    def test_buyer_can_only_mutate_own_campaign_lander(self) -> None:
        buyer_id = uuid4()
        actor = SimpleNamespace(id=buyer_id, role_name=RoleName.BUYER)

        LanderAdminService._ensure_buyer_owns_lander(
            actor=actor,
            lander=SimpleNamespace(
                tracking_link=SimpleNamespace(buyer_id=buyer_id)
            ),
        )

        with self.assertRaises(HTTPException) as raised:
            LanderAdminService._ensure_buyer_owns_lander(
                actor=actor,
                lander=SimpleNamespace(
                    tracking_link=SimpleNamespace(buyer_id=uuid4())
                ),
            )

        self.assertEqual(raised.exception.status_code, 404)

    async def test_buyer_cannot_attach_lander_to_an_existing_link(self) -> None:
        service = LanderAdminService.__new__(LanderAdminService)
        service._ensure_lander_project_access = AsyncMock()
        actor = SimpleNamespace(id=uuid4(), role_name=RoleName.BUYER)
        data = SimpleNamespace(campaign=None, tracking_link_id=uuid4())

        with self.assertRaises(HTTPException) as raised:
            await service.create_lander(
                project_id=uuid4(),
                data=data,
                actor=actor,
            )

        self.assertEqual(raised.exception.status_code, 403)

class BuyerBotSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_buyer_bot_link_does_not_store_unused_pixel_credentials(self) -> None:
        project_id = uuid4()
        bot = SimpleNamespace(id=uuid4(), name="Bot A", bot_username="bot_a")
        buyer = SimpleNamespace(
            id=uuid4(),
            name="Buyer One",
            buyer_fb_pixel_id="123456789012345",
            buyer_fb_capi_token="secret-token",
        )
        service = BuyerBotService.__new__(BuyerBotService)
        service.state_store = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "project_id": str(project_id),
                    "bot_id": str(bot.id),
                }
            )
        )
        service._buyer_has_project = AsyncMock(return_value=True)
        service._list_client_bots = AsyncMock(return_value=[bot])
        service._generate_unique_ref_code = AsyncMock(return_value="direct-code")
        service._build_client_start_link = Mock(
            return_value="https://telegram.me/bot_a?start=direct-code"
        )
        service._clear_flow_state = AsyncMock()
        service.telegram = SimpleNamespace(send_message=AsyncMock())
        service.db = SimpleNamespace(
            add=Mock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )

        await service._finish_create_link(123, buyer, "Direct campaign")

        created_link = service.db.add.call_args.args[0]
        self.assertIsNone(created_link.fb_pixel_id)
        self.assertIsNone(created_link.fb_capi_token)
        self.assertFalse(created_link.fb_campaign_enabled)

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
