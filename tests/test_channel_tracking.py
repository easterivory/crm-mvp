from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.lander_urls import build_channel_tracking_url
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.schemas.lander import LanderTrackingCampaignCreate
from app.schemas.telegram import (
    TelegramChatMember,
    TelegramMessage,
    TelegramUpdate,
    TelegramUser,
)
from app.schemas.tracking import TrackingLinkCreate
from app.services.channel_subscription_service import ChannelSubscriptionService
from app.services.facebook_channel_event_service import FacebookChannelEventService
from app.services.lander_service import LanderService
from app.services.telegram_service import TelegramService, TelegramStartPayload
from app.services.tracking_metrics_service import TrackingMetricsService


def test_existing_tracking_payload_keeps_bot_destination_by_default() -> None:
    bot_id = uuid4()

    payload = TrackingLinkCreate.model_validate(
        {"bot_id": bot_id, "title": "Legacy bot link"}
    )

    assert payload.destination_type == "bot"
    assert payload.bot_id == bot_id
    assert payload.channel_id is None
    assert payload.channel_join_request is False


def test_channel_tracking_payload_requires_channel_and_does_not_require_bot() -> None:
    channel_id = uuid4()

    payload = TrackingLinkCreate.model_validate(
        {
            "destination_type": "channel",
            "channel_id": channel_id,
            "title": "Channel traffic",
        }
    )

    assert payload.bot_id is None
    assert payload.channel_id == channel_id
    with pytest.raises(ValidationError):
        TrackingLinkCreate.model_validate(
            {"destination_type": "channel", "title": "Missing channel"}
        )


def test_facebook_channel_campaign_has_no_funnel_entry_requirement() -> None:
    payload = LanderTrackingCampaignCreate.model_validate(
        {
            "destination_type": "channel",
            "channel_id": uuid4(),
            "title": "Channel campaign",
        }
    )

    assert payload.bot_id is None
    assert payload.target_funnel_step_key is None
    with pytest.raises(ValidationError):
        LanderTrackingCampaignCreate.model_validate(
            {
                "destination_type": "channel",
                "channel_id": uuid4(),
                "title": "Invalid channel campaign",
                "target_funnel_step_key": "question_1",
            }
        )


def test_channel_click_url_uses_public_tracking_hop() -> None:
    assert build_channel_tracking_url(host="LP.SFERA.CYOU.", code="channel_01") == (
        "https://lp.sfera.cyou/join/channel_01"
    )


def test_telegram_channel_membership_updates_are_parsed() -> None:
    update = TelegramUpdate.model_validate(
        {
            "update_id": 901,
            "chat_member": {
                "chat": {"id": -1001234567890, "type": "channel", "title": "News"},
                "from": {"id": 1, "is_bot": False, "first_name": "Admin"},
                "date": 1786406400,
                "old_chat_member": {
                    "status": "left",
                    "user": {"id": 42, "is_bot": False, "first_name": "Lead"},
                },
                "new_chat_member": {
                    "status": "member",
                    "user": {"id": 42, "is_bot": False, "first_name": "Lead"},
                },
                "invite_link": {
                    "invite_link": "https://t.me/+invite-code",
                    "creates_join_request": False,
                },
            },
        }
    )

    assert update.chat_member is not None
    assert update.chat_member.chat.id == -1001234567890
    assert update.chat_member.invite_link is not None
    assert update.chat_member.invite_link.invite_link.endswith("invite-code")
    assert ChannelSubscriptionService._is_active_member(
        update.chat_member.new_chat_member
    )


def test_stale_channel_update_does_not_rewind_current_subscription() -> None:
    async def run() -> None:
        db = SimpleNamespace(flush=AsyncMock())
        service = ChannelSubscriptionService(db)
        current = SimpleNamespace(
            tracking_link_id=uuid4(),
            username="current",
            first_name="Current",
            last_name=None,
            status="left",
            last_event_at=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
            last_update_id=200,
            first_joined_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
            joined_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
            left_at=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        )
        service._get_subscription = AsyncMock(  # type: ignore[method-assign]
            return_value=current
        )

        await service._upsert_subscription(
            channel=SimpleNamespace(id=uuid4(), project_id=uuid4()),
            bot_id=uuid4(),
            user=TelegramUser(id=42, first_name="Old"),
            tracking_link_id=uuid4(),
            status="member",
            occurred_at=datetime(2026, 8, 11, 11, tzinfo=timezone.utc),
            update_id=199,
        )

        assert current.status == "left"
        assert current.last_update_id == 200
        db.flush.assert_not_awaited()

    asyncio.run(run())


def test_default_channel_lander_identifies_channel_and_uses_channel_copy() -> None:
    channel = SimpleNamespace(
        title="Market News",
        username="market_news",
        description="Fresh market updates",
    )
    lander = SimpleNamespace(
        slug="channel-campaign",
        description=None,
        button_text=None,
        auto_redirect_enabled=False,
        tracking_link=SimpleNamespace(
            destination_type="channel",
            channel=channel,
            bot=None,
        ),
    )

    rendered = LanderService._render_default_redirect_html(
        lander,
        "https://telegram.me/+invite-code",
        "",
    )

    assert "Market News - Telegram" in rendered
    assert "@market_news" in rendered
    assert "Telegram-канал" in rendered
    assert "Fresh market updates" in rendered
    assert ">Подписаться на канал</a>" in rendered


def test_channel_metrics_use_click_to_join_conversion_independently() -> None:
    summary = TrackingMetricsService._summary_from_values(
        {
            "clicks": 40,
            "starts": 0,
            "leads": 0,
            "channel_clicks": 40,
            "channel_join_requests": 18,
            "channel_joins": 10,
            "channel_leaves": 2,
            "channel_active_subscribers": 8,
            "spend": Decimal("25"),
        }
    )

    assert summary.channel_join_requests == 18
    assert summary.channel_joins == 10
    assert summary.channel_leaves == 2
    assert summary.channel_active_subscribers == 8
    assert summary.cr_click_to_channel_join == Decimal("25.00")
    assert summary.cr_to_lead == Decimal("0.00")


def test_channel_facebook_event_commits_membership_before_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        calls: list[str] = []
        link = SimpleNamespace(
            id=uuid4(),
            destination_type="channel",
            fb_campaign_enabled=True,
            fb_pixel_id="123456789",
            fb_capi_token="token",
            fb_event_mappings_json=[
                {
                    "source_event": "channel_subscribe",
                    "event_name": "Subscribe",
                    "enabled": True,
                    "parameters": {},
                }
            ],
            code="channel-campaign",
        )
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: link)
            ),
            commit=AsyncMock(side_effect=lambda: calls.append("commit")),
        )

        async def enqueue(**kwargs) -> str:
            assert db.commit.await_count == 1
            calls.append("queue")
            assert kwargs["tracking_link_id"] == link.id
            return "job-id"

        monkeypatch.setattr(
            "app.services.facebook_channel_event_service.enqueue_facebook_channel_event",
            enqueue,
        )

        result = await FacebookChannelEventService(db).enqueue_event(
            tracking_link_id=link.id,
            channel=SimpleNamespace(
                id=uuid4(),
                telegram_chat_id=-1001234567890,
                title="Market News",
                username="market_news",
            ),
            user=TelegramUser(id=42, first_name="Lead"),
            source_event="channel_subscribe",
            update_id=902,
            occurred_at=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        )

        assert result == "job-id"
        assert calls == ["commit", "queue"]

    asyncio.run(run())


def test_channel_link_cannot_be_used_as_bot_start_attribution() -> None:
    async def run() -> None:
        project_id = uuid4()
        bot_id = uuid4()
        service = TelegramService.__new__(TelegramService)
        service.tracking_repo = SimpleNamespace(
            get_link_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid4(),
                    project_id=project_id,
                    bot_id=bot_id,
                    destination_type="channel",
                )
            )
        )

        resolved = await service._resolve_tracking_link_id(
            TelegramStartPayload(tracking_link_id=uuid4()),
            project_id,
            bot_id,
        )

        assert resolved is None

    asyncio.run(run())


def test_channel_fallback_is_only_for_start_without_reference() -> None:
    assert not TelegramService._has_explicit_start_attribution(
        TelegramStartPayload()
    )
    assert TelegramService._has_explicit_start_attribution(
        TelegramStartPayload(ref_code="fresh-facebook")
    )
    assert TelegramService._has_explicit_start_attribution(
        TelegramStartPayload(tracking_link_id=uuid4())
    )
    assert TelegramService._has_explicit_start_attribution(
        TelegramStartPayload(start_key="lnd_fresh_facebook")
    )
    assert TelegramService._has_explicit_start_attribution(
        TelegramStartPayload(utm_key="utm_deadbeef")
    )


def test_explicit_start_replaces_older_channel_chat_attribution() -> None:
    async def run() -> None:
        project_id = uuid4()
        bot_id = uuid4()
        channel_link_id = uuid4()
        facebook_link_id = uuid4()
        current_chat = SimpleNamespace(
            id=uuid4(),
            contact_name="Lead",
            tracking_link_id=channel_link_id,
            is_imported=False,
            import_identity_pending=False,
        )
        updated_chat = SimpleNamespace(
            **vars(current_chat),
        )
        updated_chat.tracking_link_id = facebook_link_id
        service = TelegramService.__new__(TelegramService)
        service.chat_repo = SimpleNamespace(
            get_by_external=AsyncMock(return_value=current_chat),
            update_by_id=AsyncMock(return_value=updated_chat),
        )
        service.tracking_repo = SimpleNamespace(
            get_link_by_id=AsyncMock(
                return_value=SimpleNamespace(destination_type="channel")
            )
        )
        message = TelegramMessage.model_validate(
            {
                "message_id": 1,
                "chat": {"id": 42},
                "from": {"id": 42, "first_name": "Lead"},
                "text": "/start fresh-facebook",
            }
        )

        chat, should_start, reactivated = await service._find_or_create_chat(
            message,
            project_id,
            bot_id,
            tracking_link_id=facebook_link_id,
            replace_existing_channel_attribution=True,
        )

        assert chat.tracking_link_id == facebook_link_id
        assert should_start is False
        assert reactivated is False
        service.chat_repo.update_by_id.assert_awaited_once_with(
            current_chat.id,
            tracking_link_id=facebook_link_id,
        )

    asyncio.run(run())


def test_channel_fallback_does_not_replace_existing_bot_attribution() -> None:
    async def run() -> None:
        current_bot_link_id = uuid4()
        channel_link_id = uuid4()
        current_chat = SimpleNamespace(
            id=uuid4(),
            contact_name="Lead",
            tracking_link_id=current_bot_link_id,
            is_imported=False,
            import_identity_pending=False,
        )
        service = TelegramService.__new__(TelegramService)
        service.chat_repo = SimpleNamespace(
            get_by_external=AsyncMock(return_value=current_chat),
            update_by_id=AsyncMock(),
        )
        service.tracking_repo = SimpleNamespace(
            get_link_by_id=AsyncMock(
                return_value=SimpleNamespace(destination_type="bot")
            )
        )
        message = TelegramMessage.model_validate(
            {
                "message_id": 1,
                "chat": {"id": 42},
                "from": {"id": 42, "first_name": "Lead"},
                "text": "/start",
            }
        )

        chat, _, _ = await service._find_or_create_chat(
            message,
            uuid4(),
            uuid4(),
            tracking_link_id=channel_link_id,
            replace_existing_channel_attribution=True,
        )

        assert chat.tracking_link_id == current_bot_link_id
        service.chat_repo.update_by_id.assert_not_awaited()

    asyncio.run(run())


def test_start_message_snapshots_resolved_tracking_link() -> None:
    async def run() -> None:
        tracking_link_id = uuid4()
        expected = SimpleNamespace(id=uuid4())
        service = TelegramService.__new__(TelegramService)
        service.message_service = SimpleNamespace(
            create_message=AsyncMock(return_value=expected)
        )
        message = TelegramMessage.model_validate(
            {
                "message_id": 1,
                "chat": {"id": 42},
                "from": {"id": 42, "first_name": "Lead"},
                "text": "/start",
            }
        )

        result = await service._create_message(
            uuid4(),
            uuid4(),
            message,
            tracking_link_id=tracking_link_id,
        )

        assert result is expected
        data = service.message_service.create_message.await_args.kwargs["data"]
        assert data.tracking_link_id == tracking_link_id

    asyncio.run(run())


def test_link_start_metrics_use_message_snapshot_not_mutable_chat_source() -> None:
    async def run() -> None:
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one=lambda: 0)
            )
        )

        await TrackingMetricsRepository(db).aggregate_starts_by_link(
            uuid4(),
            datetime(2026, 8, 1, tzinfo=timezone.utc).date(),
            datetime(2026, 8, 11, tzinfo=timezone.utc).date(),
        )

        statement = db.execute.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        assert "messages.tracking_link_id" in sql
        assert "chats.tracking_link_id" not in sql

    asyncio.run(run())
