from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.spa import (
    _is_crm_application_domain,
    _is_technical_domain,
    _public_not_found_response,
)
from app.core.config import settings
from app.api.v1.routers.public_landers import _request_host
from app.core.facebook_events import (
    default_facebook_event_mappings,
    facebook_mapping_for_source,
    normalize_facebook_event_mappings,
    normalize_facebook_source_event,
    normalize_facebook_tag_event_rules,
)
from app.core.lander_urls import (
    build_lander_public_url,
    effective_campaign_utm_defaults,
)
from app.models.lander import ProjectDomain
from app.models.tracking import TrackingEvent
from app.repositories.tracking_repository import TrackingEventRepository
from app.repositories.tag_repository import TagRepository
from app.schemas.lander import ProjectDomainCreate, ProjectLanderUpdate
from app.schemas.tracking import FacebookEventMapping
from app.services.facebook_campaign_service import FacebookCampaignService
from app.services.facebook_capi_service import FacebookCAPIService
from app.services.lander_admin_service import LanderAdminService
from app.services.lander_service import LanderService
from app.services.domain_dns_service import DomainDnsService
from app.services.project_service import ProjectService


class FacebookEventMappingTests(unittest.TestCase):
    def test_default_mapping_contains_browser_and_server_events(self) -> None:
        mappings = default_facebook_event_mappings()

        self.assertEqual(
            facebook_mapping_for_source(mappings, "click")["event_name"],
            "Lead",
        )
        self.assertEqual(
            facebook_mapping_for_source(mappings, "user_start_bot")["event_name"],
            "Schedule",
        )
        sale = facebook_mapping_for_source(mappings, "sale")
        self.assertEqual(sale["event_name"], "Purchase")
        self.assertEqual(sale["parameters"]["currency"], "USD")

    def test_duplicate_source_event_is_rejected(self) -> None:
        duplicate = [
            {
                "source_event": "sale",
                "event_name": "Purchase",
                "enabled": True,
                "parameters": {},
            },
            {
                "source_event": "sale",
                "event_name": "Lead",
                "enabled": True,
                "parameters": {},
            },
        ]

        with self.assertRaisesRegex(ValueError, "Duplicate Facebook source event"):
            normalize_facebook_event_mappings(duplicate)

    def test_legacy_source_alias_is_normalized(self) -> None:
        self.assertEqual(normalize_facebook_source_event("subscribe_channel"), "channel_subscribe")

    def test_legacy_server_mapping_keeps_funnel_action_trigger(self) -> None:
        mappings = normalize_facebook_event_mappings(
            [
                {
                    "source_event": "registration",
                    "event_name": "CompleteRegistration",
                    "enabled": True,
                    "parameters": {},
                }
            ]
        )

        self.assertEqual(mappings[0]["triggers"], [{"type": "funnel_action"}])

    def test_status_and_tag_triggers_are_normalized(self) -> None:
        status_id = uuid4()
        tag_id = uuid4()
        mappings = normalize_facebook_event_mappings(
            [
                {
                    "source_event": "sale",
                    "event_name": "Purchase",
                    "enabled": True,
                    "parameters": {},
                    "triggers": [
                        {"type": "lead_status", "value": str(status_id)},
                        {"type": "lead_tag", "value": str(tag_id)},
                    ],
                }
            ]
        )

        self.assertEqual(
            mappings[0]["triggers"],
            [
                {"type": "lead_status", "value": str(status_id)},
                {"type": "lead_tag", "value": str(tag_id)},
            ],
        )

    def test_automatic_event_rejects_manual_trigger(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot have custom triggers"):
            normalize_facebook_event_mappings(
                [
                    {
                        "source_event": "bot_start",
                        "event_name": "Schedule",
                        "enabled": True,
                        "parameters": {},
                        "triggers": [{"type": "funnel_action"}],
                    }
                ]
            )

    def test_project_tag_event_rules_are_normalized_and_deduplicated(self) -> None:
        tag_id = uuid4()
        normalized = normalize_facebook_tag_event_rules(
            [{"tag_id": tag_id, "source_event": "registration"}]
        )

        self.assertEqual(
            normalized,
            [{"tag_id": str(tag_id), "source_event": "registration"}],
        )
        with self.assertRaisesRegex(ValueError, "Duplicate Facebook tag event rule"):
            normalize_facebook_tag_event_rules([*normalized, *normalized])

    def test_project_tag_event_rule_rejects_automatic_event(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be triggered by a project tag"):
            normalize_facebook_tag_event_rules(
                [{"tag_id": uuid4(), "source_event": "bot_start"}]
            )

    def test_deleting_domain_does_not_orphan_delete_landers(self) -> None:
        cascade = ProjectDomain.landers.property.cascade

        self.assertNotIn("delete", cascade)
        self.assertNotIn("delete-orphan", cascade)
        self.assertIs(ProjectDomain.landers.property.passive_deletes, True)

    def test_technical_domain_is_host_aware(self) -> None:
        request = SimpleNamespace(headers={"host": "lp.sfera.cyou:443"})

        self.assertIs(_is_technical_domain(request), True)

    def test_public_not_found_page_is_neutral_english_html(self) -> None:
        response = _public_not_found_response()
        body = response.body.decode("utf-8")

        self.assertEqual(response.status_code, 404)
        self.assertIn('<html lang="en">', body)
        self.assertIn("Page unavailable", body)
        self.assertNotIn("Страница", body)

    def test_crm_ui_is_limited_to_configured_hosts(self) -> None:
        with (
            patch.object(settings, "BASE_URL", "https://sfera.cyou"),
            patch.object(settings, "CRM_PUBLIC_HOSTS", "crm-alt.example.com"),
        ):
            self.assertIs(
                _is_crm_application_domain(
                    SimpleNamespace(headers={"host": "sfera.cyou:443"})
                ),
                True,
            )
            self.assertIs(
                _is_crm_application_domain(
                    SimpleNamespace(headers={"host": "crm-alt.example.com"})
                ),
                True,
            )
            self.assertIs(
                _is_crm_application_domain(
                    SimpleNamespace(headers={"host": "promo.example.com"})
                ),
                False,
            )

    def test_crm_ui_host_falls_back_to_technical_domain_parent(self) -> None:
        with (
            patch.object(settings, "BASE_URL", "http://localhost:8000"),
            patch.object(settings, "CRM_PUBLIC_HOSTS", ""),
            patch.object(settings, "LANDER_TECH_DOMAIN", "lp.sfera.cyou"),
        ):
            self.assertIs(
                _is_crm_application_domain(
                    SimpleNamespace(headers={"host": "sfera.cyou"})
                ),
                True,
            )
            self.assertIs(
                _is_crm_application_domain(
                    SimpleNamespace(headers={"host": "lp.sfera.cyou"})
                ),
                False,
            )

    def test_forwarded_host_is_used_for_parked_domain_resolution(self) -> None:
        request = SimpleNamespace(
            headers={
                "host": "lp.sfera.cyou",
                "x-forwarded-host": "promo.example.com, lp.sfera.cyou",
            }
        )

        self.assertEqual(_request_host(request), "promo.example.com")

    def test_explicit_null_domain_is_preserved_by_update_schema(self) -> None:
        update = ProjectLanderUpdate(domain_id=None)

        self.assertIn("domain_id", update.model_fields_set)
        self.assertIsNone(update.domain_id)

    def test_tracking_event_has_unique_hour_bucket(self) -> None:
        constraint_names = {
            constraint.name for constraint in TrackingEvent.__table__.constraints
        }

        self.assertIn("uq_tracking_events_link_bucket", constraint_names)

    def test_facebook_lander_url_contains_visible_default_utm(self) -> None:
        defaults = effective_campaign_utm_defaults(
            {},
            tracking_code="fb-campaign-42",
            is_facebook_campaign=True,
        )

        url = build_lander_public_url(
            host="promo.example.com",
            slug="landing-1",
            utm_defaults=defaults,
        )

        self.assertEqual(
            url,
            "https://promo.example.com/l/landing-1?"
            "utm_source=facebook&utm_medium=paid_social&utm_campaign=fb-campaign-42",
        )

    def test_custom_utm_values_have_priority(self) -> None:
        defaults = effective_campaign_utm_defaults(
            {
                "utm_source": "fb_ads",
                "utm_medium": "cpc",
                "utm_campaign": "{{campaign.name}}",
            },
            tracking_code="fallback-code",
            is_facebook_campaign=True,
        )

        self.assertEqual(defaults["utm_source"], "fb_ads")
        self.assertEqual(defaults["utm_medium"], "cpc")
        self.assertEqual(defaults["utm_campaign"], "{{campaign.name}}")

    def test_cname_check_accepts_technical_and_bunny_targets(self) -> None:
        service = DomainDnsService(technical_domain="lp.sfera.cyou")

        self.assertIs(service._is_expected_target("lp.sfera.cyou."), True)
        self.assertIs(service._is_expected_target("campaign-zone.b-cdn.net."), True)
        self.assertIs(service._is_expected_target("unrelated.example.com."), False)

    def test_domain_routing_accepts_crm_health_response(self) -> None:
        response = httpx.Response(
            200,
            json={
                "status": "ok",
                "components": {"api": "ok", "database": "ok", "redis": "ok"},
            },
        )

        result = DomainDnsService._routing_result_from_response(
            "promo.example.com",
            response,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.status_code, 200)

    def test_domain_routing_reports_bunny_loop_with_pull_zone(self) -> None:
        response = httpx.Response(
            508,
            headers={"cdn-pullzone": "6137671", "errorcode": "108"},
        )

        result = DomainDnsService._routing_result_from_response(
            "promo.example.com",
            response,
        )

        self.assertFalse(result.verified)
        self.assertIn("CDN-цикл", result.error or "")
        self.assertIn("6137671", result.error or "")

    def test_domain_routing_reports_self_redirect(self) -> None:
        response = httpx.Response(
            301,
            headers={
                "location": "https://promo.example.com/health",
                "cdn-pullzone": "6046144",
            },
        )

        result = DomainDnsService._routing_result_from_response(
            "promo.example.com",
            response,
        )

        self.assertFalse(result.verified)
        self.assertIn("сам на себя", result.error or "")


class LanderPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_readding_soft_deleted_domain_reactivates_same_record(self) -> None:
        project_id = uuid4()
        now = datetime.now(timezone.utc)
        domain = ProjectDomain(
            id=uuid4(),
            project_id=project_id,
            domain_name="promo.example.com",
            is_active=False,
            created_at=now,
            updated_at=now,
        )
        result = SimpleNamespace(scalar_one_or_none=lambda: domain)
        db = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        service = LanderAdminService(db)
        service._ensure_admin_project_access = AsyncMock()

        created = await service.create_domain(
            project_id=project_id,
            data=ProjectDomainCreate(domain_name="promo.example.com"),
            actor=SimpleNamespace(),
        )

        self.assertEqual(created.id, domain.id)
        self.assertIs(domain.is_active, True)
        db.flush.assert_awaited_once()

    async def test_click_increment_is_atomic_and_uses_utc_hour(self) -> None:
        db = SimpleNamespace(execute=AsyncMock())
        repository = TrackingEventRepository(db)

        await repository.increment_lander_click(
            project_id=uuid4(),
            tracking_link_id=uuid4(),
            occurred_at=datetime(2026, 7, 12, 14, 37, 18, tzinfo=timezone.utc),
        )

        statement = db.execute.await_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        self.assertIn("ON CONFLICT ON CONSTRAINT uq_tracking_events_link_bucket", sql)
        self.assertIn("tracking_events.clicks + excluded.clicks", sql)
        self.assertIn(
            datetime(2026, 7, 12, 14, 0, tzinfo=timezone.utc),
            compiled.params.values(),
        )


class FacebookCampaignParameterTests(unittest.TestCase):
    def test_purchase_parameters_resolve_lead_and_tracking_context(self) -> None:
        service = FacebookCampaignService.__new__(FacebookCampaignService)
        project = SimpleNamespace(name="Project One")
        lead = SimpleNamespace(
            id=uuid4(),
            name="Anna",
            phone="+1 555 100 200",
            age=29,
            country="US",
            custom_fields={"expected_start_amount": "1250.50"},
            project=project,
        )
        link = SimpleNamespace(
            id=uuid4(),
            code="fb-code",
            ref_code="fb-code",
            buyer=SimpleNamespace(name="Buyer One"),
            buyer_name="Buyer One",
            bot=SimpleNamespace(name="Client Bot"),
        )

        rendered = service._render_parameters(
            {
                "value": "{{lead.expected_start_amount}}",
                "currency": "usd",
                "content_name": "{{project.name}} / {{tracking.code}}",
            },
            lead=lead,
            tracking_link=link,
        )

        self.assertEqual(rendered["value"], 1250.5)
        self.assertEqual(rendered["currency"], "USD")
        self.assertEqual(rendered["content_name"], "Project One / fb-code")

    def test_event_id_is_stable_for_same_business_event(self) -> None:
        values = {
            "tracking_link_id": uuid4(),
            "lead_id": uuid4(),
            "source_event": "contact",
            "event_reference": "cycle-1",
        }
        first = FacebookCampaignService.build_event_id(**values)
        second = FacebookCampaignService.build_event_id(**values)

        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 100)

    def test_purchase_value_falls_back_to_legacy_budget(self) -> None:
        service = FacebookCampaignService.__new__(FacebookCampaignService)
        lead = SimpleNamespace(
            id=uuid4(),
            name="Legacy Lead",
            phone=None,
            age=None,
            country=None,
            custom_fields={"budget": "750"},
            project=None,
        )
        link = SimpleNamespace(
            id=uuid4(),
            code="legacy",
            ref_code="legacy",
            buyer=None,
            buyer_name=None,
            bot=None,
        )

        rendered = service._render_parameters(
            {"value": "{{lead.expected_start_amount}}", "currency": "USD"},
            lead=lead,
            tracking_link=link,
        )

        self.assertEqual(rendered["value"], 750)


class FacebookCampaignTriggerTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _campaign_lead(
        *,
        mappings: list[dict],
        project_rules: list[dict] | None = None,
    ) -> SimpleNamespace:
        link = SimpleNamespace(
            id=uuid4(),
            fb_campaign_enabled=True,
            fb_pixel_id="123456789012345",
            fb_capi_token="token",
            fb_event_mappings_json=mappings,
        )
        chat = SimpleNamespace(
            tracking_link=link,
            current_cycle_started_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
        return SimpleNamespace(
            id=uuid4(),
            chat=chat,
            project_id=uuid4(),
            project=SimpleNamespace(
                facebook_tag_event_rules=project_rules or [],
            ),
            created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    async def test_tag_rule_queues_registration_without_funnel_action(self) -> None:
        tag_id = uuid4()
        lead = self._campaign_lead(
            mappings=[
                {
                    "source_event": "registration",
                    "event_name": "CompleteRegistration",
                    "enabled": True,
                    "parameters": {},
                    "triggers": [{"type": "lead_tag", "value": str(tag_id)}],
                }
            ]
        )
        service = FacebookCampaignService(SimpleNamespace())
        service._load_lead = AsyncMock(return_value=lead)
        service._enqueue_mapping = AsyncMock(return_value="job-1")

        queued = await service.enqueue_triggered_events(
            lead_id=lead.id,
            trigger_type="lead_tag",
            trigger_value=tag_id,
        )

        self.assertEqual(queued, ["job-1"])
        service._enqueue_mapping.assert_awaited_once()
        call = service._enqueue_mapping.await_args.kwargs
        self.assertEqual(call["source_event"], "registration")
        self.assertIn("crm_rule:registration:", call["event_reference"])

    async def test_project_tag_rule_queues_campaign_event(self) -> None:
        tag_id = uuid4()
        lead = self._campaign_lead(
            mappings=[
                {
                    "source_event": "registration",
                    "event_name": "CompleteRegistration",
                    "enabled": True,
                    "parameters": {},
                    "triggers": [{"type": "funnel_action"}],
                }
            ],
            project_rules=[
                {"tag_id": str(tag_id), "source_event": "registration"}
            ],
        )
        service = FacebookCampaignService(SimpleNamespace())
        service._load_lead = AsyncMock(return_value=lead)
        service._enqueue_mapping = AsyncMock(return_value="job-project-rule")

        queued = await service.enqueue_tag_added(lead_id=lead.id, tag_id=tag_id)

        self.assertEqual(queued, ["job-project-rule"])
        service._enqueue_mapping.assert_awaited_once()
        custom_data = service._enqueue_mapping.await_args.kwargs["extra_custom_data"]
        self.assertEqual(custom_data["crm_trigger_scope"], "project")

    async def test_matching_project_and_campaign_tag_rules_queue_once(self) -> None:
        tag_id = uuid4()
        lead = self._campaign_lead(
            mappings=[
                {
                    "source_event": "sale",
                    "event_name": "Purchase",
                    "enabled": True,
                    "parameters": {"currency": "USD"},
                    "triggers": [{"type": "lead_tag", "value": str(tag_id)}],
                }
            ],
            project_rules=[{"tag_id": str(tag_id), "source_event": "sale"}],
        )
        service = FacebookCampaignService(SimpleNamespace())
        service._load_lead = AsyncMock(return_value=lead)
        service._enqueue_mapping = AsyncMock(return_value="job-once")

        queued = await service.enqueue_tag_added(lead_id=lead.id, tag_id=tag_id)

        self.assertEqual(queued, ["job-once"])
        service._enqueue_mapping.assert_awaited_once()
        custom_data = service._enqueue_mapping.await_args.kwargs["extra_custom_data"]
        self.assertEqual(custom_data["crm_trigger_scope"], "project_and_campaign")

    async def test_unrelated_tag_does_not_queue_event(self) -> None:
        configured_tag_id = uuid4()
        lead = self._campaign_lead(
            mappings=[
                {
                    "source_event": "sale",
                    "event_name": "Purchase",
                    "enabled": True,
                    "parameters": {},
                    "triggers": [
                        {"type": "lead_tag", "value": str(configured_tag_id)}
                    ],
                }
            ]
        )
        service = FacebookCampaignService(SimpleNamespace())
        service._load_lead = AsyncMock(return_value=lead)
        service._enqueue_mapping = AsyncMock(return_value="unexpected")

        queued = await service.enqueue_triggered_events(
            lead_id=lead.id,
            trigger_type="lead_tag",
            trigger_value=uuid4(),
        )

        self.assertEqual(queued, [])
        service._enqueue_mapping.assert_not_awaited()

    async def test_status_only_mapping_is_not_fired_by_funnel_action(self) -> None:
        status_id = uuid4()
        lead = self._campaign_lead(
            mappings=[
                {
                    "source_event": "registration",
                    "event_name": "CompleteRegistration",
                    "enabled": True,
                    "parameters": {},
                    "triggers": [
                        {"type": "lead_status", "value": str(status_id)}
                    ],
                }
            ]
        )
        service = FacebookCampaignService(SimpleNamespace())
        service._load_lead = AsyncMock(return_value=lead)
        service._enqueue_mapping = AsyncMock(return_value="unexpected")

        queued = await service.enqueue_mapped_event(
            lead_id=lead.id,
            source_event="registration",
            event_reference="funnel:step:cycle",
        )

        self.assertIsNone(queued)
        service._enqueue_mapping.assert_not_awaited()

    async def test_trigger_validation_accepts_pydantic_mapping_models(self) -> None:
        service = FacebookCampaignService(SimpleNamespace())
        mapping = FacebookEventMapping(
            source_event="registration",
            event_name="CompleteRegistration",
            triggers=[{"type": "funnel_action"}],
        )

        normalized = await service.validate_mapping_triggers(
            project_id=uuid4(),
            mappings=[mapping],
        )

        self.assertEqual(normalized[0]["triggers"], [{"type": "funnel_action"}])


class FacebookProjectTagRuleValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_rule_rejects_tag_from_another_project(self) -> None:
        tag_id = uuid4()
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: []),
                )
            )
        )
        service = ProjectService(db)

        with self.assertRaises(HTTPException) as context:
            await service._validate_facebook_tag_event_rules(
                project_id=uuid4(),
                value=[{"tag_id": str(tag_id), "source_event": "registration"}],
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn(str(tag_id), str(context.exception.detail))

    async def test_tag_assignment_insert_is_atomic_and_idempotent(self) -> None:
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))
        repository = TagRepository(db)

        added = await repository.add_tag_to_lead(uuid4(), uuid4())

        self.assertTrue(added)
        statement = db.execute.await_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ON CONFLICT (lead_id, tag_id) DO NOTHING", sql)


class FacebookCAPIPayloadTests(unittest.TestCase):
    def test_payload_contains_dedup_source_and_hashed_user_data(self) -> None:
        lead = SimpleNamespace(
            id=uuid4(),
            name="Anna Smith",
            phone="+1 (555) 100-2000",
            country="US",
            custom_fields={
                "first_name": "Anna",
                "last_name": "Smith",
                "email": "Anna@example.com",
                "fb_data": {
                    "fbp": "fb.1.123.456",
                    "fbc": "fb.1.123.click",
                    "client_ip_address": "203.0.113.10",
                    "client_user_agent": "Browser/1.0",
                },
            },
            chat=SimpleNamespace(external_user_id="123456789"),
        )

        payload = FacebookCAPIService.build_payload(
            event_name="Purchase",
            lead=lead,
            event_time=1_800_000_000,
            custom_data={"value": 1250.5, "currency": "usd"},
            event_id="crm_event_123",
            event_source_url="https://lp.sfera.cyou/l/example?utm_source=facebook",
            test_event_code="TEST12345",
        )

        event = payload["data"][0]
        self.assertEqual(event["event_id"], "crm_event_123")
        self.assertEqual(event["event_source_url"], "https://lp.sfera.cyou/l/example?utm_source=facebook")
        self.assertEqual(event["custom_data"]["currency"], "USD")
        self.assertEqual(payload["test_event_code"], "TEST12345")
        self.assertEqual(
            event["user_data"]["external_id"][0],
            FacebookCAPIService.hash_data("123456789"),
        )
        self.assertNotEqual(event["user_data"]["em"][0], "Anna@example.com")


class FacebookLanderMarkupTests(unittest.TestCase):
    def test_campaign_markup_uses_mapping_and_browser_context_bridge(self) -> None:
        link = SimpleNamespace(
            id=uuid4(),
            fb_campaign_enabled=True,
            fb_pixel_id="123456789012345",
            fb_event_mappings_json=default_facebook_event_mappings(),
        )

        markup = LanderService._render_pixel_markup(
            [],
            [],
            tracking_link=link,
            browser_event_seed="seed123",
            bridge_url="/l/example/bridge/start_1234567890",
        )

        self.assertIn("ViewContent", markup)
        self.assertIn("__crmSyncFacebookContext", markup)
        self.assertIn("/l/example/bridge/start_1234567890", markup)
        self.assertIn("eventID", markup)
        self.assertIn("_fbp", markup)


if __name__ == "__main__":
    unittest.main()
