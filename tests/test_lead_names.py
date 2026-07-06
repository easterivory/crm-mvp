import asyncio
from types import MethodType, SimpleNamespace
from uuid import uuid4

from app.core.lead_names import compose_lead_name, resolve_lead_names, split_lead_name
from app.schemas.lead import LeadUpdate
from app.schemas.telegram import TelegramMessage
from app.services.funnel_block_registry import LEAD_FIELD_KEYS
from app.services.lead_service import LeadService
from app.services.telegram_service import TelegramService


def test_telegram_profile_keeps_last_name_separate_from_username():
    message = TelegramMessage.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 100},
            "from": {
                "id": 100,
                "first_name": "Виктор",
                "last_name": "Смирнов",
                "username": "smmirnovvictor",
            },
            "text": "/start",
        }
    )

    assert message.from_user is not None
    assert message.from_user.last_name == "Смирнов"
    assert TelegramService._contact_name_from_message(message) == "Виктор Смирнов"
    assert TelegramService._telegram_profile_fields(message) == ("Виктор", "Смирнов")


def test_legacy_name_parser_removes_telegram_username_from_surname():
    assert split_lead_name(
        "Виктор @smmirnovvictor",
        username="smmirnovvictor",
    ) == ("Виктор", None)
    assert compose_lead_name("Виктор", "Смирнов") == "Виктор Смирнов"


def test_explicit_profile_fields_override_legacy_contaminated_name():
    lead = type(
        "LeadLike",
        (),
        {
            "name": "Виктор @smmirnovvictor",
            "username": "smmirnovvictor",
            "custom_fields": {"first_name": "Виктор", "last_name": "Смирнов"},
        },
    )()

    assert resolve_lead_names(lead) == ("Виктор", "Смирнов")


def test_funnel_registry_exposes_profile_name_fields():
    assert "first_name" in LEAD_FIELD_KEYS
    assert "last_name" in LEAD_FIELD_KEYS


def test_manual_lead_profile_update_persists_first_and_last_name():
    lead = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        chat_id=uuid4(),
        name="Виктор @smmirnovvictor",
        username="smmirnovvictor",
        phone=None,
        preferred_call_time=None,
        call_time_text=None,
        custom_fields={},
    )

    class LeadRepo:
        async def get_active(self, lead_id, project_id):
            return lead if lead_id == lead.id and project_id == lead.project_id else None

        async def update_contact(self, lead_id, project_id, **values):
            assert lead_id == lead.id
            assert project_id == lead.project_id
            for key, value in values.items():
                setattr(lead, key, value)
            return lead

    class Scoring:
        async def update_lead_score(self, lead_id):
            assert lead_id == lead.id

    async def no_audit(self, **kwargs):
        return None

    async def passthrough(self, updated_lead):
        return updated_lead

    service = LeadService.__new__(LeadService)
    service.lead_repo = LeadRepo()
    service.scoring = Scoring()
    service._log_contact_updates = MethodType(no_audit, service)
    service._lead_out = MethodType(passthrough, service)

    result = asyncio.run(
        service.update_contact(
            lead.id,
            lead.project_id,
            LeadUpdate(first_name="Виктор", last_name="Смирнов"),
            uuid4(),
        )
    )

    assert result.name == "Виктор Смирнов"
    assert result.custom_fields["first_name"] == "Виктор"
    assert result.custom_fields["last_name"] == "Смирнов"
    assert result.custom_fields["__crm_name_override"] is True


def test_telegram_profile_does_not_overwrite_manual_crm_name():
    lead = SimpleNamespace(
        custom_fields={
            "first_name": "Анна",
            "last_name": "Петрова",
            "__crm_name_override": True,
        }
    )
    message = TelegramMessage.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 100},
            "from": {
                "id": 100,
                "first_name": "Telegram",
                "last_name": "Name",
            },
            "text": "Привет",
        }
    )
    service = TelegramService.__new__(TelegramService)
    service.lead_repo = SimpleNamespace(update_contact=lambda *args, **kwargs: None)

    result = asyncio.run(
        service._sync_lead_telegram_profile(lead, message, uuid4())
    )

    assert result is lead
    assert resolve_lead_names(result) == ("Анна", "Петрова")
