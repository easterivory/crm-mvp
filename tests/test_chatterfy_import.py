import asyncio
import copy
import os
from uuid import uuid4

import httpx
import pytest

from app.services.chatterfy_export_service import ChatterfyExportError, ChatterfyReadClient
from app.services.chatterfy_import_service import (
    ChatterfyStagingImporter, PROVENANCE, archive_report, create_staging_links, prepare_chat, source_key,
    is_manual_history_chat, manual_import_fields,
)
from scripts.chatterfy_prepare import mapping_template

SOURCE = "019f2c6d-dc0e-72ee-8792-3cc410f797f4"
USERNAME = "Andrey_smirniy_nobot"
DATE = "2026-08-01T00:00:00+03:00"


def archive():
    return {"pagination_complete": True, "chat": {"id": "c1", "bot_id": SOURCE,
        "external_id": "12345678901", "name": "QA", "username": "qa_user", "created_at": DATE,
        "status": "waiting", "tags": ["source-tag"], "current_step_id": "age-step",
        "lead": {"campaign_id": "campaign", "source_id": "oldCode", "params": {"utm_source": "telegram"}},
        "read_state": {"incoming_unread_count": 1}},
        "messages": [
            {"id": "m1", "chat_id": "c1", "type": "message", "sender_type": "incoming", "content": "/start t_oldCode",
             "created_at": DATE, "status": "ready", "external_id": "999"},
            {"id": "m2", "chat_id": "c1", "type": "message", "sender_type": "outcoming", "content": "Question",
             "created_at": "2026-08-01T00:01:00+03:00", "status": "ready", "sender": "old-operator", "reply_message_id": "m1"},
            {"id": "m3", "chat_id": "c1", "type": "message", "sender_type": "outcoming", "content": "Unsent",
             "created_at": "2026-08-01T00:02:00+03:00", "status": "schedule"},
        ]}


def prepare(value=None):
    return prepare_chat(value or archive(), source_bot_id=SOURCE, source_username=USERNAME)


def test_prepare_retains_source_and_step_without_inventing_funnel_or_replaying_pending():
    item = prepare()
    assert item.telegram_id == "12345678901"
    assert [m["id"] for m in item.messages] == ["m1", "m2"]
    assert item.provenance["excluded_delivery_ids"] == ["m3"]
    assert item.provenance["current_step_id"] == "age-step"
    assert item.provenance["resume_approved"] is False
    assert item.provenance["params"]["utm_source"] == "telegram"
    mapping = mapping_template([item], source_bot_id=SOURCE, source_username=USERNAME, created_from=DATE)
    assert mapping["destination"]["bot_id"] is None
    assert mapping["tag_map"] == {"source-tag": None}
    assert mapping["link_proposals"][0]["observed_legacy_payload"] == "t_oldCode"
    assert mapping["link_proposals"][0]["code"].startswith("chf_")
    report = archive_report([item])
    assert report["crm_writes"] == 0 and report["complete_cohort"] is False


@pytest.mark.parametrize("change", [
    lambda a: a.update(pagination_complete=False),
    lambda a: a["chat"].update(bot_id="another-bot"),
    lambda a: a["chat"].update(created_at="2026-07-31T20:59:59Z"),
    lambda a: a["chat"].update(external_id="@someone"),
    lambda a: a["chat"].update(external_id="9223372036854775808"),
    lambda a: a["chat"].update(status="unknown"),
    lambda a: a["messages"][0].update(chat_id="other"),
    lambda a: a["messages"][0].update(sender_type="unknown"),
    lambda a: a["messages"][0].update(status="unknown"),
    lambda a: a["messages"].append(copy.deepcopy(a["messages"][0])),
])
def test_invalid_archives_fail_closed(change):
    value = archive(); change(value)
    with pytest.raises(ChatterfyExportError):
        prepare(value)


def test_later_start_is_not_silently_substituted_for_original_source():
    value = archive(); value["messages"][0]["content"] = "/start t_later"
    item = prepare(value)
    assert item.provenance["source_id"] == "oldCode"
    assert "source_and_start_payload_differ" in item.warnings
    with pytest.raises(ChatterfyExportError, match="share a Telegram identity"):
        archive_report([item, item])


def test_organic_source_is_not_recreated_as_a_paid_campaign_from_a_later_start():
    value = archive(); value["chat"]["lead"]["provider_type"] = "organic"
    value["messages"][0]["content"] = "/start t_later"
    item = prepare(value)
    template = mapping_template([item], source_bot_id=SOURCE, source_username=USERNAME, created_from=DATE)
    assert template["link_proposals"] == [] and template["source_map"] == {}
    assert item.provenance["provider_type"] == "organic"


def test_metadata_allowlist_does_not_permit_writes_or_arbitrary_urls():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET" and request.headers["ApiKey"] == "private"
        return httpx.Response(200, json={"data": [], "pagination": {"has_more": False}})
    client = ChatterfyReadClient("private", transport=httpx.MockTransport(handler), interval=0)
    try:
        client.metadata(f"/bots/v1/{SOURCE}/tags")
        for path in (f"/bots/v1/{SOURCE}/tags?delete=true", "/messages/v1/send", "https://external/key", "/campaigns/v1/../secret"):
            with pytest.raises(ChatterfyExportError): client.metadata(path)
        assert len(requests) == 1
    finally:
        client.close()


def test_only_explicit_manual_history_provenance_is_blocked_and_normal_chat_never_queries_db():
    from types import SimpleNamespace
    assert manual_import_fields({PROVENANCE: {"schema": 1, "mode": "manual"}})
    for fields in (None, {}, {PROVENANCE: "bad"}, {PROVENANCE: {"schema": 1, "mode": "resume"}}):
        assert not manual_import_fields(fields)
    assert asyncio.run(is_manual_history_chat(None, SimpleNamespace(is_imported=False))) is False


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_staging_is_idempotent_scoped_atomic_and_has_no_automation_side_effects():
    async def run():
        from sqlalchemy import func, select, text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from app.models import Base, Bot, Chat, Lead, LeadStatus, Message, Project, Tag, LeadTag, TrackingLink
        from app.models.funnel import ChatFunnelState, FunnelScheduledJob
        from app.models.telegram_delivery import RuntimeDispatch
        from app.models.tracking import TrackingEvent
        from app.models.advertising import AdvertisingEnrollment
        schema = "chatterfy_" + uuid4().hex
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            async with root.begin() as db: await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db: await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="QA import", slug="qa-import", project_format="gambling")
                status = LeadStatus(code="import_manual", name="Imported manual")
                db.add_all([project, status]); await db.flush()
                bot = Bot(project_id=project.id, name="Tokenless draft")
                tag = Tag(project_id=project.id, name="VIP")
                db.add_all([bot, tag]); await db.commit()
                item = prepare()
                template = mapping_template([item], source_bot_id=SOURCE, source_username=USERNAME, created_from=DATE)
                key = source_key("campaign", "oldCode")
                mapping = await create_staging_links(db, project_id=project.id, bot_id=bot.id, proposals=template["link_proposals"])
                assert mapping == await create_staging_links(db, project_id=project.id, bot_id=bot.id, proposals=template["link_proposals"])
                importer = ChatterfyStagingImporter(db, project_id=project.id, bot_id=bot.id, source_bot_id=SOURCE,
                    source_username=USERNAME, status_id=status.id, tag_map={"source-tag": tag.id},
                    source_map={key: UUID(value) for key, value in mapping.items()})
                # Exact legacy deep-link payloads are already supported by the normal
                # resolver; no wildcard fallback or cross-bot alias is introduced.
                from app.services.telegram_service import TelegramService
                payload = TelegramService._extract_start_payload("/start t_oldCode")
                assert payload.ref_code == "t_oldCode"
                legacy = await create_staging_links(db, project_id=project.id, bot_id=bot.id, proposals=[{
                    "source_key": source_key("legacy-campaign", "oldCode"), "code": "t_oldCode", "name": "Legacy direct link"}])
                resolver = TelegramService(db)
                expected_legacy = UUID(legacy[source_key("legacy-campaign", "oldCode")])
                assert await resolver._resolve_tracking_link_id(payload, project.id, bot.id) == expected_legacy
                assert await resolver._resolve_tracking_link_id(payload, project.id, uuid4()) is None
                collision = TrackingLink(project_id=project.id, bot_id=bot.id, name="Existing",
                    title="Existing", code="occupied", ref_code="occupied")
                db.add(collision); await db.flush()
                with pytest.raises(ChatterfyExportError, match="collision"):
                    await create_staging_links(db, project_id=project.id, bot_id=bot.id, proposals=[{
                        "source_key": source_key("other", "other"), "code": "occupied", "name": "Must not replace"}])
                assert collision.name == "Existing"
                assert (await importer.import_chat(item))["status"] == "ready"
                assert await db.scalar(select(func.count()).select_from(Chat)) == 0
                invalid = archive(); invalid["chat"]["name"] = "x" * 256
                with pytest.raises(ChatterfyExportError, match="contact fields"):
                    await importer.import_chat(prepare(invalid))
                assert await db.scalar(select(func.count()).select_from(Chat)) == 0
                assert (await importer.import_chat(item, dry_run=False))["status"] == "imported"
                await db.commit()
                assert (await importer.import_chat(item, dry_run=False))["status"] == "already_imported"
                assert await db.scalar(select(func.count()).select_from(Message)) == 2
                chat = await db.scalar(select(Chat))
                lead = await db.scalar(select(Lead))
                messages = list((await db.scalars(select(Message).order_by(Message.created_at))).all())
                assert chat.is_imported and chat.external_user_id == "12345678901"
                assert chat.created_at.year == 2026 and chat.created_at.month == 7
                assert not chat.is_read and chat.import_identity_pending is False
                assert lead.custom_fields[PROVENANCE]["current_step_id"] == "age-step"
                assert lead.manager_id is None
                assert all(m.external_message_id is None and m.funnel_processed_at for m in messages)
                assert messages[1].sender_type == "manager" and messages[1].operator_id is None
                assert messages[1].reply_to_message_id == messages[0].id
                assert messages[0].tracking_link_id == chat.tracking_link_id
                assert await db.scalar(select(func.count()).select_from(LeadTag)) == 1
                for model in (ChatFunnelState, FunnelScheduledJob, RuntimeDispatch, TrackingEvent, AdvertisingEnrollment):
                    assert await db.scalar(select(func.count()).select_from(model)) == 0
                from types import SimpleNamespace
                from unittest.mock import AsyncMock
                service = TelegramService.__new__(TelegramService)
                service.db = db
                service.bot_repo = SimpleNamespace(get_active=AsyncMock())
                await service._process_runtime_or_legacy(chat=chat, project_id=project.id, bot_id=bot.id,
                    user_message=None, start_requested=True, fresh_lifecycle=False)
                await service._process_callback_runtime_or_legacy(chat=chat, project_id=project.id, bot_id=bot.id,
                    user_message=None, callback_query=None, fallback_text="old button")
                service.bot_repo.get_active.assert_not_awaited()
                from app.services.advertising_service import AdvertisingService
                assert await AdvertisingService(db).protected_reason(chat, None) == "manual_history_import"
                # A same-identity card which was not created by this importer is never merged.
                clone = archive(); clone["chat"]["id"] = "different-source-chat"
                for m in clone["messages"]: m["chat_id"] = "different-source-chat"
                with pytest.raises(ChatterfyExportError, match="no overwrite"):
                    await importer.import_chat(prepare(clone), dry_run=False)
                changed = archive(); changed["messages"][0]["content"] = "changed"
                with pytest.raises(ChatterfyExportError, match="no overwrite"):
                    await importer.import_chat(prepare(changed), dry_run=False)
                assert messages[0].body == "/start t_oldCode"
                original_source = importer.source_map
                importer.source_map = {key: uuid4()}
                with pytest.raises(ChatterfyExportError, match="different destination"):
                    await importer.import_chat(item)
                importer.source_map = original_source
                original_tag = importer.tag_map
                importer.tag_map = {}
                with pytest.raises(ChatterfyExportError, match="Every source tag"):
                    await importer.import_chat(item)
                importer.tag_map = original_tag
                bot.telegram_token = "123:local-test-only"; await db.flush()
                with pytest.raises(ChatterfyExportError, match="tokenless"):
                    await importer.import_chat(item)
                await db.rollback()
                # Removed history remains a tombstone; media prevents any apply.
                other = archive(); other["chat"].update(id="c2", external_id="4321")
                for m in other["messages"]: m["chat_id"] = "c2"
                other["messages"][0]["files"] = [{"type": "photo", "url": "https://example/photo"}]
                with pytest.raises(ChatterfyExportError, match="attachment migration"):
                    await importer.import_chat(prepare(other), dry_run=False)
                assert await db.scalar(select(func.count()).select_from(Chat)) == 1
        finally:
            await engine.dispose()
            async with root.begin() as db: await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    from uuid import UUID
    asyncio.run(run())
