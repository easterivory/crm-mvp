import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.exc import DBAPIError

from app.models import Base, Bot, Chat, Lead, Project, Role, User, TrackingLink
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, ChatFunnelState
from app.models.gambling_offer import GamblingOffer, OfferLink, OfferPayoutPolicy, OfferPayoutVersion, OfferPayoutAssignment, OfferConversion
from app.models.lead_event import LeadEvent
from app.models.lead_status import LeadStatus
from app.models.postback import PostbackEndpoint, PostbackReceipt
from app.schemas.gambling_offer import OfferWrite, PayoutPolicyWrite, PayoutTerms, QualificationWrite
from app.schemas.postback import PostbackParameterMapping, LeadEventCreate
from app.services.gambling_offer_service import GamblingOfferService, personalize_url
from app.services.offer_payout_service import OfferPayoutService, payout_total, period_bounds
from app.services.postback_contract_service import PostbackContractService

PG = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")


def test_query_personalization_preserves_other_bytes_and_plain_links_are_not_normalized():
    url = "https://example.org/path?a=x%20y&a=z+v&blank=&sub=old&raw=%2f%2F#section"
    result = personalize_url(url, "sub", "new_token")
    assert result == "https://example.org/path?a=x%20y&a=z+v&blank=&raw=%2f%2F&sub=new_token#section"
    assert personalize_url("https://example.org?sub=1&sub=2", "sub", "new").count("sub=") == 1


@pytest.mark.parametrize("mode,count,expected", [("excess", 10, "100"), ("excess", 11, "115"),
    ("retroactive", 10, "150"), ("retroactive", 11, "165")])
def test_threshold_semantics_decimal_no_floating_point(mode, count, expected):
    terms = PayoutTerms(rate="10", tier_mode=mode, tiers=[{"threshold": 10, "rate": "15"}])
    assert payout_total(count, terms) == Decimal(expected)
    assert payout_total(10, PayoutTerms(rate="0.10", tiers=[{"threshold": 10, "bonus": "2.01"}])) == Decimal("3.01")


def test_calendar_periods_moscow_and_custom_are_end_exclusive():
    start, end = period_bounds(date(2026, 11, 8), PayoutTerms(period="week"))
    assert start.isoformat() == "2026-11-01T21:00:00+00:00" and end - start == timedelta(days=7)
    assert period_bounds(date(2026, 11, 8), PayoutTerms(period="custom", period_from="2026-11-01", period_to="2026-11-07")) is None
    with pytest.raises(ValueError): PayoutTerms(tiers=[{"threshold": 5, "rate": 2}, {"threshold": 5, "bonus": 1}])
    with pytest.raises(ValueError): OfferWrite(name="x", partner_name="PP", source_url="javascript:alert(1)")
    with pytest.raises(ValueError): OfferWrite(name="x", partner_name="PP", source_url="https://127.0.0.1/path")


@asynccontextmanager
async def fixture(migrate=False):
    schema = "offers_" + uuid4().hex
    root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
    engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with root.begin() as db: await db.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as db: await db.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            p = Project(name="Offer QA", slug="qa", project_format="gambling")
            status = LeadStatus(code="new", name="New")
            role = Role(name="super_admin")
            db.add_all([p, status, role]); await db.flush()
            bot = Bot(project_id=p.id, name="QA")
            actor_row = User(role_id=role.id, email="qa@example.org", name="QA", password_hash="unused")
            db.add_all([bot, actor_row]); await db.flush()
            link = TrackingLink(project_id=p.id, bot_id=bot.id, name="Source A", title="Source A", code="qa", ref_code="qa")
            db.add(link); await db.flush()
            leads = []
            for n in range(3):
                chat = Chat(project_id=p.id, bot_id=bot.id, external_chat_id=str(n + 100), external_user_id=str(n + 100), tracking_link_id=link.id)
                db.add(chat); await db.flush()
                lead = Lead(project_id=p.id, chat_id=chat.id, status_id=status.id)
                db.add(lead); await db.flush(); leads.append(lead.id)
            await db.commit()
            actor = SimpleNamespace(id=actor_row.id, role_name="super_admin")
            yield sessions, p.id, actor, leads, bot.id, link.id
    finally:
        await engine.dispose()
        async with root.begin() as db: await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await root.dispose()


def offer_data(policy_id=None, postbacks=True):
    return OfferWrite(name="QA offer", partner_name="PP", source_url="https://example.org/path?a=x%20y",
        payout_policy_id=policy_id, postbacks_enabled=postbacks,
        identifier_parameter="sub1" if postbacks else None,
        postback_mapping=PostbackParameterMapping(identifier_param="click", event_type_param="type", amount_param="amount",
            currency_param="currency", external_event_id_param="transaction", occurred_at_param="at",
            bind_external_id_param="player", event_aliases={"signup": "registration"}) if postbacks else None)


async def configured(sessions, pid, actor):
    async with sessions() as db:
        policy = await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="CPA", partner_name="PP",
            terms=PayoutTerms(rate="10", min_deposit="5")))
        offer = await GamblingOfferService(db).save(pid, actor, offer_data(policy["id"]))
        endpoint = await db.get(PostbackEndpoint, offer["endpoint_id"])
        assert endpoint.is_active is False
        endpoint.is_active = True
        await db.commit()
        return offer["id"], endpoint.id, endpoint.secret_token, policy["id"]


@PG
def test_issuance_frozen_urls_two_leads_plain_mode_and_project_boundaries():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source_id):
            oid, eid, token, policy = await configured(sessions, pid, actor)
            async with sessions() as db:
                service = GamblingOfferService(db)
                first = await service.issue(await db.get(Lead, leads[0]), oid, "run-1")
                second = await service.issue(await db.get(Lead, leads[1]), oid, "run-1")
                assert first.token != second.token and len(first.token) >= 32
                assert parse_qs(urlsplit(first.issued_url).query)["sub1"] == [first.token]
                assert (await service.issue(await db.get(Lead, leads[0]), oid, "run-1")).id == first.id
                row = await db.get(GamblingOffer, oid); row.source_url = "https://example.org/new?x=2"
                await db.flush()
                assert (await service.issue(await db.get(Lead, leads[0]), oid, "run-1")).issued_url == first.issued_url
                assert "/new?x=2&" in (await service.issue(await db.get(Lead, leads[0]), oid, "run-2")).issued_url
                ordinary = await service.save(pid, actor, offer_data(postbacks=False))
                plain = await service.issue(await db.get(Lead, leads[0]), ordinary["id"], "run")
                assert plain.issued_url == "https://example.org/path?a=x%20y" and plain.endpoint_id is None
                assert "payout_policy_id" not in (await service.list_offers(pid, actor))[0]
                manager = SimpleNamespace(id=actor.id, role_name="manager", project_id=pid)
                with pytest.raises(HTTPException) as e: await OfferPayoutService(db).policies(pid, manager)
                assert e.value.status_code == 403
                with pytest.raises(HTTPException): await service.save(pid, manager, offer_data())
                other = Project(name="Other", slug="other", project_format="gambling"); db.add(other); await db.flush()
                lead = await db.get(Lead, leads[2]); lead.project_id = other.id
                with pytest.raises(HTTPException): await service.issue(lead, oid, "wrong-project")
    asyncio.run(run())


@PG
def test_callbacks_concurrency_rd_player_only_frozen_attribution_and_fd_date_terms():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source_id):
            oid, eid, secret, policy_id = await configured(sessions, pid, actor)
            async with sessions() as db:
                link = await GamblingOfferService(db).issue(await db.get(Lead, leads[0]), oid, "run")
                click = link.token
                await db.commit()
            async def receive(payload):
                async with sessions() as db:
                    r = await PostbackContractService(db).receive(token=secret, method="POST", query={}, body=payload)
                    await db.commit(); return r
            occurred = datetime.now(timezone.utc)
            reg = {"click": click, "type": "signup", "player": "player-1", "at": occurred.isoformat()}
            results = await asyncio.gather(*(receive(reg) for _ in range(8)))
            assert sum(r.status == "processed" for r in results) == 1
            assert all(r.status in {"processed", "duplicate"} for r in results)
            # Change terms AFTER the link was issued but BEFORE the FD; FD uses v2.
            async with sessions() as db:
                await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="CPA", partner_name="PP",
                    terms=PayoutTerms(rate="25", min_deposit="5")), policy_id)
                await db.commit()
            fd_at = datetime.now(timezone.utc)
            fd = {"player": "player-1", "type": "fd", "amount": "10", "currency": "USD", "at": fd_at.isoformat(), "transaction": "fd-1"}
            results = await asyncio.gather(*(receive(fd) for _ in range(8)))
            assert sum(r.status == "processed" for r in results) == 1
            assert (await receive({**fd, "transaction": "fd-duplicate-new-id"})).status == "duplicate"
            assert (await receive({**fd, "amount": "11"})).status == "conflict"
            assert (await receive({**fd, "type": "rd", "transaction": "rd-1"})).status == "processed"
            assert (await receive({**fd, "type": "rd", "transaction": "rd-2"})).status == "processed"
            assert (await receive({**fd, "type": "rd", "transaction": ""})).status == "invalid"
            assert (await receive({**fd, "player": "unknown", "transaction": "unknown"})).status == "unmatched"
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 4
                conversion = await db.scalar(select(OfferConversion).where(OfferConversion.event_type == "deposit"))
                version = await db.get(OfferPayoutVersion, conversion.payout_version_id)
                assert version.version == 2 and conversion.qualified is True
                report = await OfferPayoutService(db).report(pid, actor, fd_at.date())
                assert report["rows"][0]["estimated_commission"] == "25.00"
                event = await db.get(LeadEvent, conversion.event_id)
                assert event.tracking_link_id == source_id
                lead = await db.get(Lead, leads[0]); chat = await db.get(Chat, lead.chat_id); chat.tracking_link_id = None
                await db.commit()
            assert (await receive({**fd, "type": "rd", "transaction": "rd-3"})).status == "processed"
            async with sessions() as db:
                event = await db.scalar(select(LeadEvent).where(LeadEvent.external_event_id == "rd-3"))
                assert event.tracking_link_id == source_id
    asyncio.run(run())


@PG
@pytest.mark.parametrize("mode,expected_v1,expected_v2", [("excess", "20.00", "47.00"), ("retroactive", "40.00", "47.00")])
def test_partner_group_counter_does_not_reset_on_rate_version_and_bonus_is_not_duplicated(mode, expected_v1, expected_v2):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                payout = await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Group", partner_name="PP",
                    count_scope="partner_group", terms=PayoutTerms(rate="10", tier_mode=mode, tiers=[{"threshold": 2, "rate": "20"}])))
                policy_id = payout["id"]
                offers = [await GamblingOfferService(db).save(pid, actor, offer_data(policy_id)) for _ in range(2)]
                endpoints = []
                for offer in offers:
                    endpoint = await db.get(PostbackEndpoint, offer["endpoint_id"]); endpoint.is_active = True
                    endpoints.append(endpoint.secret_token)
                await db.commit()
            for n in range(3):
                if n == 2:
                    async with sessions() as db:
                        await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Group", partner_name="PP",
                            count_scope="partner_group", terms=PayoutTerms(rate="30", tier_mode=mode,
                                tiers=[{"threshold": 2, "rate": "40"}, {"threshold": 3, "bonus": "7"}])), policy_id)
                        await db.commit()
                async with sessions() as db:
                    link = await GamblingOfferService(db).issue(await db.get(Lead, leads[n]), offers[n % 2]["id"], "run")
                    event_at = datetime.now(timezone.utc)
                    result = await PostbackContractService(db).receive(token=endpoints[n % 2], method="POST", query={},
                        body={"click": link.token, "type": "fd", "transaction": f"fd-{n}", "amount": "10", "currency": "USD", "at": event_at.isoformat()})
                    assert result.status == "processed"
                    await db.commit()
            async with sessions() as db:
                rows = (await OfferPayoutService(db).report(pid, actor, datetime.now(timezone.utc).date()))["rows"]
                by_version = {r["version"]: r for r in rows}
                assert by_version[1]["estimated_commission"] == expected_v1
                assert by_version[2]["estimated_commission"] == expected_v2
                assert all(r["offer_id"] is None for r in rows)
    asyncio.run(run())


@PG
def test_late_fd_uses_previous_version_and_a_new_parser_keeps_old_endpoint_working():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            oid, old_eid, old_secret, policy_id = await configured(sessions, pid, actor)
            async with sessions() as db:
                link = await GamblingOfferService(db).issue(await db.get(Lead, leads[0]), oid, "old-run")
                old_url, old_token = link.issued_url, link.token
                await db.commit()
            fd_at = datetime.now(timezone.utc)
            async with sessions() as db:
                await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="CPA", partner_name="PP", terms=PayoutTerms(rate="99")), policy_id)
                changed = offer_data(policy_id)
                changed.postback_mapping.identifier_param = "new_click"
                updated = await GamblingOfferService(db).save(pid, actor, changed, oid)
                assert updated["endpoint_id"] != old_eid
                assert (await db.get(PostbackEndpoint, old_eid)).is_active
                assert (await GamblingOfferService(db).issue(await db.get(Lead, leads[0]), oid, "old-run")).issued_url == old_url
                await db.commit()
            async with sessions() as db:
                result = await PostbackContractService(db).receive(token=old_secret, method="POST", query={},
                    body={"click": old_token, "type": "fd", "transaction": "late-fd", "amount": "10", "currency": "USD", "at": fd_at.isoformat()})
                assert result.status == "processed"
                conversion = await db.scalar(select(OfferConversion))
                assert (await db.get(OfferPayoutVersion, conversion.payout_version_id)).version == 1
                await db.commit()
    asyncio.run(run())


@PG
def test_manager_api_never_exposes_commission_or_raw_postback_and_manual_fd_requires_review():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                p = await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Private commission", partner_name="PP", terms=PayoutTerms(rate="777")))
                offer = await GamblingOfferService(db).save(pid, actor, offer_data(p["id"], postbacks=False))
                manager = SimpleNamespace(id=actor.id, project_id=pid, role_name="manager")
                await GamblingOfferService(db).manual_event(pid, manager, leads[0], LeadEventCreate(offer_id=offer["id"],
                    event_type="fd", amount="50.25", currency="USD", payload={"private_pp_commission": "777"}))
                await db.commit()
            from app.api.v1.routers.gambling_offers import router, lead_router
            from app.api.v1.dependencies import get_db, get_current_user
            app = FastAPI(); app.include_router(router); app.include_router(lead_router)
            app.dependency_overrides[get_current_user] = lambda: manager
            async def database():
                async with sessions() as db:
                    yield db
                    await db.commit()
            app.dependency_overrides[get_db] = database
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://qa") as client:
                summary = await client.get(f"/leads/{leads[0]}/deposit-summary", params={"project_id": str(pid)})
                assert summary.status_code == 200
                body = summary.json()
                assert body["totals"] == [{"currency": "USD", "amount": "50.25", "unknown_amount_count": 0}]
                assert body["automatic_tracking"] is False and body["data_complete"] is False
                assert '"777"' not in summary.text and "private_pp_commission" not in summary.text and "payload" not in summary.text and "payout" not in summary.text
                for path in ("/gambling-offers/payout-policies", "/gambling-offers/finance?day=2026-11-06", f"/gambling-offers/{offer['id']}/settings", "/gambling-offers/qualification"):
                    assert (await client.get(path, params={"project_id": str(pid)})).status_code == 403
                listing = await client.get("/gambling-offers", params={"project_id": str(pid)})
                assert listing.status_code == 200 and "payout" not in listing.text and "777" not in listing.text
            async with sessions() as db:
                conversion = await db.scalar(select(OfferConversion))
                assert conversion.qualified is None and conversion.qualification_reason == "manual_review_required"
                await OfferPayoutService(db).qualify(pid, actor, conversion.id, QualificationWrite(qualified=True, reason="Manual check"))
                await db.commit()
                with pytest.raises(HTTPException):
                    await OfferPayoutService(db).qualify(pid, actor, conversion.id, QualificationWrite(qualified=False, reason="Second decision"))
                report = await OfferPayoutService(db).report(pid, actor, datetime.now(timezone.utc).date())
                assert report["rows"][0]["estimated_commission"] == "777.00"
    asyncio.run(run())


@PG
def test_offer_template_is_blocked_without_configuration_and_html_links_are_escaped():
    async def run():
        from app.schemas.funnel import FunnelValidationOut
        from app.services.funnel_service import FunnelService
        from app.services.funnel_runtime_service import FunnelRuntimeService
        from app.repositories.funnel_repository import FunnelRepository
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                lead = await db.get(Lead, leads[0])
                funnel = Funnel(project_id=pid, bot_id=bid, name="Offer funnel")
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="draft")
                target = FunnelVersion(funnel_id=funnel.id, version_number=2, status="draft")
                db.add_all([version, target]); await db.flush()
                step = FunnelStep(funnel_version_id=version.id, key="q", title="Q", step_type="input", block_type="generic_input")
                db.add(step); await db.flush()
                state = ChatFunnelState(chat_id=lead.chat_id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=step.id, entered_step_at=datetime.now(timezone.utc), waiting_for_answer=True)
                db.add(state); await db.flush()
                graph = SimpleNamespace(model_dump=lambda **kwargs: {"text": "{{offer_link}}"})
                validation = FunnelValidationOut(can_publish=True)
                await FunnelService(db)._validate_offer_variable(version.id, pid, graph, validation, strict=True)
                assert not validation.can_publish and validation.errors[0].code == "offer_link_unconfigured"
                with pytest.raises(HTTPException): await FunnelRuntimeService(db)._render_text_template(lead.chat_id, "Go {{offer_link}}")
                ordinary_data = offer_data(postbacks=False)
                ordinary_data.source_url = "https://example.org/path?a=x%20y&b=2"
                ordinary = await GamblingOfferService(db).save(pid, actor, ordinary_data)
                version.offer_id = ordinary["id"]; await db.flush()
                html = await FunnelRuntimeService(db)._render_text_template(lead.chat_id, '<a href="{{offer_link}}">Go</a>', html=True)
                assert '{{' not in html and 'a=x%20y&amp;b=2' in html
                from app.core.telegram_formatting import telegram_html
                assert telegram_html(FunnelService._offer_preview_html('<a href="{{offer_link}}">Go</a>'))[0] == "Go"
                with pytest.raises(ValueError): telegram_html('<a href="{{offer_link}}">Go</a>')
                await FunnelRepository(db).clone_graph(version.id, target.id)
                assert target.offer_id == version.offer_id
                other = Project(name="Other", slug="other", project_format="gambling"); db.add(other); await db.flush()
                other_bot = Bot(project_id=other.id, name="Other"); db.add(other_bot); await db.flush()
                other_funnel = Funnel(project_id=other.id, bot_id=other_bot.id, name="Other"); db.add(other_funnel); await db.flush()
                other_version = FunnelVersion(funnel_id=other_funnel.id, version_number=1, status="draft")
                db.add(other_version); await db.flush()
                await FunnelRepository(db).clone_graph(version.id, other_version.id)
                assert other_version.offer_id is None
    asyncio.run(run())


@PG
def test_new_completed_funnel_run_gets_a_new_link_but_repeats_in_one_run_do_not():
    async def run():
        from unittest.mock import AsyncMock
        from app.services.funnel_runtime_service import FunnelRuntimeService
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            offer_id, _, _, _ = await configured(sessions, pid, actor)
            async with sessions() as db:
                lead = await db.get(Lead, leads[0])
                funnel = Funnel(project_id=pid, bot_id=bid, name="Runs"); db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published", offer_id=offer_id)
                db.add(version); await db.flush()
                step = FunnelStep(funnel_version_id=version.id, key="start", title="Start", step_type="trigger", block_type="start")
                db.add(step); await db.flush()
                runtime = FunnelRuntimeService(db)
                runtime._execute_from_step = AsyncMock(return_value=step)
                runtime._log_runtime_step = AsyncMock()
                await runtime.start_funnel_for_chat(chat_id=lead.chat_id, funnel_id=funnel.id, funnel_version_id=version.id)
                state = await runtime.repo.get_chat_funnel_state(lead.chat_id)
                first_run = state.runtime_json["offer_run_key"]
                service = GamblingOfferService(db)
                first = await service.template_link(lead.chat_id, state)
                assert await service.template_link(lead.chat_id, state) == first
                state.completed_at = datetime.now(timezone.utc); await db.flush()
                await runtime.start_funnel_for_chat(chat_id=lead.chat_id, funnel_id=funnel.id, funnel_version_id=version.id)
                state = await runtime.repo.get_chat_funnel_state(lead.chat_id)
                assert state.runtime_json["offer_run_key"] != first_run
                assert await service.template_link(lead.chat_id, state) != first
                assert await db.scalar(select(func.count()).select_from(OfferLink)) == 2
    asyncio.run(run())


@PG
def test_free_text_payout_conditions_need_admin_review_without_a_partner_confirmation_flag():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                policy = await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Extra checks", partner_name="PP",
                    terms=PayoutTerms(rate="100", conditions_note="Проверить требования ПП перед зачётом")))
                offer = await GamblingOfferService(db).save(pid, actor, offer_data(policy["id"]))
                endpoint = await db.get(PostbackEndpoint, offer["endpoint_id"]); endpoint.is_active = True
                link = await GamblingOfferService(db).issue(await db.get(Lead, leads[0]), offer["id"], "run")
                await db.commit()
                result = await PostbackContractService(db).receive(token=endpoint.secret_token, method="POST", query={}, body={
                    "click": link.token, "type": "fd", "transaction": "extra-checks", "amount": "10", "currency": "USD", "at": datetime.now(timezone.utc).isoformat()})
                assert result.status == "processed"
                row = await db.scalar(select(OfferConversion))
                assert row.qualified is None and row.qualification_reason == "additional_conditions_require_review"
                report = await OfferPayoutService(db).report(pid, actor, datetime.now(timezone.utc).date())
                assert report["rows"][0]["estimated_commission"] == "0.00" and report["rows"][0]["pending_fd"] == 1
    asyncio.run(run())


@PG
def test_additive_migration_keeps_legacy_data_and_does_not_assign_offers_or_recalculate_events():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                event = LeadEvent(project_id=pid, lead_id=leads[0], event_type="deposit", source="manual", amount=Decimal("12.34"),
                    currency="USD", occurred_at=datetime.now(timezone.utc), payload_json={"legacy": "keep"})
                funnel = Funnel(project_id=pid, bot_id=bid, name="Legacy"); db.add_all([event, funnel]); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.commit()
                event_id, version_id = event.id, version.id
                # Reconstruct the pre-0096 schema, retaining the legacy rows.
                await db.execute(text('ALTER TABLE funnel_versions DROP COLUMN offer_id'))
                for name in ("offer_conversions", "offer_links", "offer_payout_assignments", "gambling_offers", "offer_payout_versions", "offer_payout_policies"):
                    await db.execute(text(f'DROP TABLE {name}'))
                await db.commit()
                spec = importlib.util.spec_from_file_location("offers_migration", "alembic/versions/20261106_0096_gambling_offers.py")
                migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
                connection = await db.connection()
                def upgrade(sync):
                    with Operations.context(MigrationContext.configure(sync)): migration.upgrade()
                await connection.run_sync(upgrade); await db.commit()
                await db.refresh(event); await db.refresh(version)
                assert event.id == event_id and event.amount == Decimal("12.34") and event.payload_json == {"legacy": "keep"}
                assert version.id == version_id and version.offer_id is None
                for model in (GamblingOffer, OfferLink, OfferConversion, OfferPayoutVersion, OfferPayoutAssignment):
                    assert await db.scalar(select(func.count()).select_from(model)) == 0
                assert await db.scalar(select(func.count()).select_from(Lead)) == 3
    asyncio.run(run())


@PG
def test_pending_partner_qualification_updates_once_and_cannot_take_another_players_identity():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                policy = await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Qualified", partner_name="PP",
                    terms=PayoutTerms(rate="42", qualification_param="qualified")))
                offer = await GamblingOfferService(db).save(pid, actor, offer_data(policy["id"]))
                endpoint = await db.get(PostbackEndpoint, offer["endpoint_id"]); endpoint.is_active = True
                secret = endpoint.secret_token
                a = await GamblingOfferService(db).issue(await db.get(Lead, leads[0]), offer["id"], "run")
                b = await GamblingOfferService(db).issue(await db.get(Lead, leads[1]), offer["id"], "run")
                click_a, click_b = a.token, b.token
                await db.commit()
            timestamp = datetime.now(timezone.utc).isoformat()
            fd = {"click": click_a, "player": "player-a", "type": "fd", "transaction": "fd-a", "amount": "10", "currency": "USD", "at": timestamp, "qualified": "pending"}
            async def receive(payload, dry_run=False):
                async with sessions() as db:
                    result = await PostbackContractService(db).receive(token=secret, method="POST", query={}, body=payload, dry_run=dry_run)
                    await db.commit(); return result
            assert (await receive(fd)).status == "processed"
            assert (await receive({**fd, "click": click_b, "player": "player-b", "type": "reg", "transaction": "reg-b"})).status == "processed"
            assert (await receive({**fd, "player": "player-b", "qualified": "approved"})).status == "conflict"
            changed_time = {**fd, "transaction": "fd-a-other", "qualified": "approved",
                            "at": (datetime.fromisoformat(timestamp) - timedelta(hours=1)).isoformat()}
            assert (await receive(changed_time, dry_run=True))["status"] == "conflict"
            assert (await receive(changed_time)).status == "conflict"
            assert (await receive({**fd, "qualified": "approved"}, dry_run=True))["status"] == "matched"
            async with sessions() as db:
                row = await db.scalar(select(OfferConversion).where(OfferConversion.event_type == "deposit"))
                assert row.qualified is None  # Dry run did not mutate money or qualifications.
            results = await asyncio.gather(*(receive({**fd, "qualified": "approved"}) for _ in range(8)))
            assert sum(r.status == "processed" for r in results) == 1
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadEvent).where(LeadEvent.event_type == "deposit")) == 1
                report = await OfferPayoutService(db).report(pid, actor, datetime.now(timezone.utc).date())
                assert report["rows"][0]["estimated_commission"] == "42.00"
    asyncio.run(run())


@PG
def test_offer_migration_database_failure_rolls_back_all_ddl_and_retains_legacy_rows(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                await db.execute(text('ALTER TABLE funnel_versions DROP COLUMN offer_id'))
                for name in ("offer_conversions", "offer_links", "offer_payout_assignments", "gambling_offers", "offer_payout_versions", "offer_payout_policies"):
                    await db.execute(text(f'DROP TABLE {name}'))
                await db.commit()
                spec = importlib.util.spec_from_file_location("offers_failed_migration", "alembic/versions/20261106_0096_gambling_offers.py")
                migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
                original = migration.op.create_foreign_key

                def invalid_foreign_key(name, source, target, local, remote):
                    return original(name, source, "missing_offer_table_for_rollback_test", local, remote)

                # Fail in PostgreSQL after the tables and new column were created.
                with monkeypatch.context() as patch:
                    patch.setattr(migration.op, "create_foreign_key", invalid_foreign_key)
                    connection = await db.connection()
                    def upgrade(sync):
                        with Operations.context(MigrationContext.configure(sync)): migration.upgrade()
                    with pytest.raises(DBAPIError): await connection.run_sync(upgrade)
                    await db.rollback()
                assert await db.scalar(text("SELECT to_regclass('gambling_offers')")) is None
                assert await db.scalar(text("SELECT to_regclass('offer_payout_policies')")) is None
                assert await db.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'funnel_versions' AND column_name = 'offer_id'")) == 0
                assert set((await db.scalars(select(Lead.id))).all()) == set(leads)
                assert await db.scalar(select(func.count()).select_from(TrackingLink)) == 1
    asyncio.run(run())


@PG
def test_missing_fd_time_does_not_use_intake_time_for_money_and_admin_can_supply_actual_date():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, source):
            async with sessions() as db:
                policy = await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Date test", partner_name="PP", terms=PayoutTerms(rate="11")))
                data = offer_data(policy["id"]); data.postback_mapping.occurred_at_param = None
                offer = await GamblingOfferService(db).save(pid, actor, data)
                endpoint = await db.get(PostbackEndpoint, offer["endpoint_id"]); endpoint.is_active = True
                link = await GamblingOfferService(db).issue(await db.get(Lead, leads[0]), offer["id"], "run")
                await db.commit()
                actual_fd_at = datetime.now(timezone.utc)
                await OfferPayoutService(db).save_policy(pid, actor, PayoutPolicyWrite(name="Date test", partner_name="PP", terms=PayoutTerms(rate="99")), policy["id"])
                await db.commit()
                result = await PostbackContractService(db).receive(token=endpoint.secret_token, method="POST", query={},
                    body={"click": link.token, "type": "fd", "transaction": "time-missing", "amount": "10", "currency": "USD"})
                assert result.status == "processed"
                row = await db.scalar(select(OfferConversion))
                assert row.qualified is None and row.payout_version_id is None and not row.event_time_confirmed
                with pytest.raises(HTTPException):
                    await OfferPayoutService(db).qualify(pid, actor, row.id, QualificationWrite(qualified=True, reason="Without time"))
                await OfferPayoutService(db).qualify(pid, actor, row.id, QualificationWrite(qualified=True, reason="Confirmed date", occurred_at=actual_fd_at))
                assert row.qualified is True and row.event_time_confirmed
                assert (await db.get(OfferPayoutVersion, row.payout_version_id)).version == 1
                assert row.review_json["previous_payout_version_id"] is None
                report = await OfferPayoutService(db).report(pid, actor, actual_fd_at.date())
                assert report["rows"][0]["estimated_commission"] == "11.00"
    asyncio.run(run())
