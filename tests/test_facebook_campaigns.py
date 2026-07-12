from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.api.spa import _is_technical_domain
from app.api.v1.routers.public_landers import _request_host
from app.core.facebook_events import (
    default_facebook_event_mappings,
    facebook_mapping_for_source,
    normalize_facebook_event_mappings,
    normalize_facebook_source_event,
)
from app.models.lander import ProjectDomain
from app.models.tracking import TrackingEvent
from app.repositories.tracking_repository import TrackingEventRepository
from app.schemas.lander import ProjectDomainCreate, ProjectLanderUpdate
from app.services.facebook_campaign_service import FacebookCampaignService
from app.services.facebook_capi_service import FacebookCAPIService
from app.services.lander_admin_service import LanderAdminService
from app.services.lander_service import LanderService


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

    def test_deleting_domain_does_not_orphan_delete_landers(self) -> None:
        cascade = ProjectDomain.landers.property.cascade

        self.assertNotIn("delete", cascade)
        self.assertNotIn("delete-orphan", cascade)
        self.assertIs(ProjectDomain.landers.property.passive_deletes, True)

    def test_technical_domain_is_host_aware(self) -> None:
        request = SimpleNamespace(headers={"host": "lp.sfera.cyou:443"})

        self.assertIs(_is_technical_domain(request), True)

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
