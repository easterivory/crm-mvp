from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv4Network
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.partner import PartnerRequestConfig
from app.services.partner_service import PartnerService
from app.services.postback_service import PostbackService


def make_integration(**request_overrides):
    request_config = {
        "method": "POST",
        "body_format": "json",
        "payload_template": {},
        "headers": {},
        "query_params": {},
        "secret_variables": {},
        "generator_config": {"password_length": 12, "ipv4_cidrs": []},
        **request_overrides,
    }
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        field_mapping={},
        required_fields=[],
        request_config=request_config,
        auth_config={},
        auth_token=None,
        auth_type="header",
        response_mapping={
            "status_path": "success",
            "success_values": ["true"],
            "duplicate_values": ["duplicate"],
            "rejected_values": ["false"],
            "error_path": "error",
            "external_id_path": "leadId",
        },
    )


def make_lead():
    buyer = SimpleNamespace(
        id=uuid4(),
        name="Buyer One",
        email="buyer@example.test",
        buyer_telegram_id=123,
    )
    tracking = SimpleNamespace(
        id=uuid4(),
        code="track-code",
        ref_code="track-code",
        title="Campaign",
        buyer_name=None,
        buyer=buyer,
    )
    chat = SimpleNamespace(
        external_user_id="99112233",
        contact_name="Ivan Telegramov",
        tracking_link=tracking,
        bot=SimpleNamespace(id=uuid4(), name="Sales Bot", bot_username="sales_bot"),
    )
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        chat_id=uuid4(),
        chat=chat,
        project=SimpleNamespace(name="Project One"),
        name="Ivan",
        phone="+7 (999) 123-45-67",
        username="ivan_tg",
        age=31,
        country="KZ",
        preferred_call_time=None,
        call_time_text="evening",
        has_card=True,
        score_percent=80,
        custom_fields={"campaign": "summer"},
        created_at=datetime.now(timezone.utc),
    )


def service():
    return PostbackService.__new__(PostbackService)


def test_nested_payload_template_renders_lead_tracking_secrets_and_generators():
    integration = make_integration(
        payload_template={
            "affc": "{{secret.AFFC}}",
            "profile": {
                "firstName": "{{lead.first_name}}",
                "lastName": "{{lead.last_name}}",
                "email": "{{lead.telegram_email}}",
                "password": "{{random.password}}",
                "phone": "{{lead.phone_digits}}",
            },
            "ip": "{{random.ipv4}}",
            "geo": "KZ",
            "comment": "TG: {{lead.telegram_id}}, campaign: {{lead.custom.campaign}}",
            "subId": "{{tracking.code}}",
            "subId_a": "{{buyer.name}}",
        },
        secret_variables={"AFFC": "secret-affc"},
        generator_config={"password_length": 18, "ipv4_cidrs": ["31.31.64.0/24"]},
    )
    integration.required_fields = ["affc", "profile.phone", "ip"]

    payload = service().build_payload(make_lead(), integration)

    assert payload["affc"] == "secret-affc"
    assert payload["profile"]["firstName"] == "Ivan"
    assert payload["profile"]["lastName"] == "Ivan"
    assert payload["profile"]["email"] == "tg99112233@lead.auto"
    assert payload["profile"]["phone"] == "79991234567"
    assert len(payload["profile"]["password"]) == 18
    assert IPv4Address(payload["ip"]) in IPv4Network("31.31.64.0/24")
    assert payload["comment"] == "TG: 99112233, campaign: summer"
    assert payload["subId"] == "track-code"
    assert payload["subId_a"] == "Buyer One"


def test_legacy_field_mapping_remains_supported():
    integration = make_integration()
    integration.field_mapping = {
        "profile.phone": "phone",
        "profile.name": "name",
    }
    integration.required_fields = ["profile.phone"]

    payload = service().build_payload(make_lead(), integration)

    assert payload["profile"]["phone"] == "+7 (999) 123-45-67"
    assert payload["profile"]["name"] == "Ivan"


def test_headers_query_and_form_request_are_rendered_from_same_context():
    integration = make_integration(
        method="PATCH",
        body_format="form",
        headers={"x-api-key": "{{secret.API_KEY}}", "x-lead": "{{lead.id}}"},
        query_params={"source": "{{tracking.code}}"},
        secret_variables={"API_KEY": "top-secret"},
    )
    lead = make_lead()
    context = service()._build_template_context(lead, integration)

    request = service()._build_request(integration, context=context)

    assert request["method"] == "PATCH"
    assert request["body_format"] == "form"
    assert request["headers"]["x-api-key"] == "top-secret"
    assert request["headers"]["x-lead"] == str(lead.id)
    assert request["params"]["source"] == "track-code"


def test_boolean_success_response_and_secret_redaction():
    integration = make_integration(secret_variables={"AFFC": "secret-affc"})

    parsed = service().parse_response(
        {"success": True, "leadId": "external-42"},
        integration,
    )
    redacted = service().redact_payload(
        {"affc": "secret-affc", "comment": "key=secret-affc"},
        integration,
    )

    assert parsed["status"] == "completed"
    assert parsed["external_id"] == "external-42"
    assert redacted == {"affc": "***", "comment": "key=***"}


def test_redacted_secret_values_are_valid_for_edit_roundtrip():
    config = PartnerRequestConfig(secret_variables={"AFFC": ""})
    assert config.secret_variables == {"AFFC": ""}


def test_name_falls_back_to_telegram_contact_name():
    integration = make_integration(
        payload_template={
            "firstName": "{{lead.first_name}}",
            "lastName": "{{lead.last_name}}",
        }
    )
    lead = make_lead()
    lead.name = None

    payload = service().build_payload(lead, integration)

    assert payload == {"firstName": "Ivan", "lastName": "Telegramov"}


def test_only_failed_partner_submissions_allow_retry():
    assert not PartnerService._has_blocking_submission(
        [SimpleNamespace(status="failed"), SimpleNamespace(status="FAILED")]
    )
    assert PartnerService._has_blocking_submission(
        [SimpleNamespace(status="failed"), SimpleNamespace(status="pending")]
    )
    assert PartnerService._has_blocking_submission(
        [SimpleNamespace(status="completed")]
    )
