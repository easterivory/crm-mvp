"""Assignment and explicit takeover against disposable PostgreSQL, without mocks."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.routers.chats import pause_chat_funnel
from app.core.constants import AuditAction, SenderType
from app.models import Base, Bot, Chat, Lead, Project, User
from app.models.audit_log import AuditLog
from app.models.chat_event_log import ChatEventLog
from app.models.funnel import ChatFunnelState, Funnel, FunnelScheduledJob, FunnelStep, FunnelVersion
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.services.assignment_service import AssignmentService
from app.services.chat_service import ChatService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.schemas.message import MessageCreate
from app.services.message_service import MessageService
from app.services.scheduled_message_service import ScheduledMessageService


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
@pytest.mark.parametrize("pause_mode", ["takeover", "text", "photo", "video_note"])
def test_assignment_preserves_runtime_and_takeover_is_explicit_scoped_and_idempotent(pause_mode):
    async def run():
        schema = "takeover_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(
            os.environ["CRM_TEST_POSTGRES_URL"],
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Takeover", slug="takeover")
                other = Project(name="Other", slug="other")
                manager_role, buyer_role, admin_role = [Role(name=name) for name in ("manager", "buyer", "admin")]
                status = LeadStatus(name="New", code="new")
                db.add_all([project, other, manager_role, buyer_role, admin_role, status])
                await db.flush()
                manager, second_manager, buyer, admin = [
                    User(project_id=project.id, role=role, name=name, email=f"{name}@test.local", password_hash="unused")
                    for name, role in [("manager", manager_role), ("second", manager_role), ("buyer", buyer_role), ("admin", admin_role)]
                ]
                bot = Bot(project_id=project.id, name="Bot", telegram_token=None)
                db.add_all([manager, second_manager, buyer, admin, bot])
                await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Existing funnel")
                db.add(funnel)
                await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version)
                await db.flush()
                step = FunnelStep(funnel_version_id=version.id, key="question", title="Question", step_type="message", block_type="message")
                db.add(step)
                await db.flush()
                chats = [Chat(project_id=project.id, bot_id=bot.id, external_chat_id=str(i), external_user_id=str(i)) for i in range(4)]
                db.add_all(chats)
                await db.flush()
                leads = [Lead(project_id=project.id, chat_id=chat.id, status_id=status.id) for chat in chats]
                db.add_all(leads)
                now = datetime.now(timezone.utc)
                states = [ChatFunnelState(
                    chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=step.id, entered_step_at=now, waiting_for_answer=True,
                    is_paused=i == 1, paused_at=now if i == 1 else None,
                    completed_at=now if i == 2 else None, runtime_json={"answers": {"name": "Arslan"}},
                ) for i, chat in enumerate(chats[:3])]
                db.add_all(states)
                await db.flush()
                jobs = [FunnelScheduledJob(
                    job_type="delayed_message", chat_id=chat.id, funnel_state_id=state.id,
                    funnel_id=funnel.id, funnel_version_id=version.id, step_id=step.id,
                    run_at=now + timedelta(minutes=5), status="pending",
                ) for chat, state in zip(chats[:2], states)]
                db.add_all(jobs)
                await db.commit()

                # Opening a chat still claims it, but must not pause its funnel.
                await ChatService(db).get_chat(chats[0].id, project.id, actor=manager)
                await db.refresh(leads[0])
                await db.refresh(chats[0])
                await db.refresh(states[0])
                await db.refresh(jobs[0])
                assert leads[0].manager_id == manager.id
                assert chats[0].assignment_expires_at > now
                assert not states[0].is_paused and jobs[0].status == "pending"
                assert states[0].waiting_for_answer
                assert states[0].runtime_json == {"answers": {"name": "Arslan"}}

                # Explicit assignment neither resumes an existing pause nor cancels jobs.
                await AssignmentService(db).assign_manager(
                    lead_id=leads[1].id, project_id=project.id, manager_id=manager.id, actor_id=admin.id,
                )
                await db.refresh(states[1])
                await db.refresh(jobs[1])
                assert states[1].is_paused and states[1].paused_at == now
                assert jobs[1].status == "pending"

                for actor in (buyer, second_manager):
                    with pytest.raises(HTTPException) as error:
                        await pause_chat_funnel(chats[0].id, project.id, actor, db)
                    assert error.value.status_code == 403
                with pytest.raises(HTTPException) as error:
                    await pause_chat_funnel(chats[0].id, other.id, admin, db)
                assert error.value.status_code == 403
                with pytest.raises(HTTPException) as error:
                    await pause_chat_funnel(uuid4(), project.id, admin, db)
                assert error.value.status_code == 409

                delivered = None
                if pause_mode != "takeover":
                    service = MessageService(db)
                    await ScheduledMessageService(db).schedule_message(
                        chat_id=chats[0].id, project_id=project.id, actor=manager,
                        scheduled_at=now + timedelta(hours=1), text="Later reply",
                        original_text=None, media_type="text", auto_translate=False,
                    )
                    # Bot sends and historical manager messages are not manual replies.
                    for sender, external_id in [(SenderType.BOT, "100"), (SenderType.MANAGER, "101")]:
                        await service.create_message(chats[0].id, project.id, MessageCreate(
                            external_message_id=external_id, sender_type=sender,
                            operator_id=manager.id if sender == SenderType.MANAGER else None,
                            body="Historical message", message_type="text",
                        ), send_to_telegram=False, translate_incoming=False)
                    # Real delivery validation fails for this tokenless test bot.
                    with pytest.raises(HTTPException) as failed:
                        await service.send_message_to_client(
                            chat_id=chats[0].id, project_id=project.id, operator_id=manager.id,
                            text="Cannot deliver", auto_translate=False,
                        )
                    assert failed.value.status_code == 502
                    await db.refresh(states[0])
                    await db.refresh(jobs[0])
                    assert not states[0].is_paused and jobs[0].status == "pending"
                    # Exercise the post-delivery persistence path used by text, media and albums.
                    delivered = await service.create_message(chats[0].id, project.id, MessageCreate(
                        external_message_id="102", sender_type=SenderType.MANAGER,
                        operator_id=manager.id, message_type=pause_mode,
                        body="Manual reply" if pause_mode == "text" else None,
                        telegram_file_id="photo-file" if pause_mode != "text" else None,
                        media_group_id="album-1" if pause_mode == "photo" else None,
                    ), send_to_telegram=False, pause_funnel_after_delivery=True)
                    control = await FunnelRuntimeService(db).get_manager_funnel_control(
                        chat_id=chats[0].id, project_id=project.id,
                    )
                    assert control["is_available"] and control["is_paused"]
                else:
                    control = await pause_chat_funnel(chats[0].id, project.id, manager, db)
                    assert control.is_available and control.is_paused
                await db.refresh(states[0])
                await db.refresh(jobs[0])
                assert states[0].paused_by_user_id == manager.id
                assert states[0].paused_at >= now
                assert states[0].waiting_for_answer
                assert states[0].runtime_json == {"answers": {"name": "Arslan"}}
                assert jobs[0].status == "cancelled"
                await db.commit()
                paused_at = states[0].paused_at
                await pause_chat_funnel(chats[0].id, project.id, manager, db)
                await db.refresh(states[0])
                assert states[0].paused_at == paused_at
                audits = (await db.execute(select(AuditLog).where(AuditLog.action == AuditAction.CHAT_FUNNEL_PAUSED))).scalars().all()
                events = (await db.execute(select(ChatEventLog).where(ChatEventLog.chat_id == chats[0].id))).scalars().all()
                assert len(audits) == 1
                assert audits[0].meta["reason"] == ("manager_takeover" if pause_mode == "takeover" else "manager_reply")
                if delivered is not None:
                    assert audits[0].meta["message_id"] == str(delivered.id)
                assert len(events) == 1 and events[0].user_id == manager.id
                assert ("перехватил" if pause_mode == "takeover" else "ручной ответ") in events[0].new_value
                if delivered is not None:
                    runtime = FunnelRuntimeService(db)
                    await runtime.repo.set_chat_funnel_paused(chat_id=chats[0].id, is_paused=False)
                    # Replaying a persisted reply must not pause a resumed funnel.
                    await service.create_message(chats[0].id, project.id, MessageCreate(
                        external_message_id="102", sender_type=SenderType.MANAGER,
                        operator_id=manager.id, body="Duplicate reply", message_type="text",
                    ), send_to_telegram=False, pause_funnel_after_delivery=True)
                    await db.refresh(states[0])
                    assert not states[0].is_paused
                    # A second album element / subsequent reply creates no extra pause event.
                    for external_id in ("103", "104"):
                        await service.create_message(chats[0].id, project.id, MessageCreate(
                            external_message_id=external_id, sender_type=SenderType.MANAGER,
                            operator_id=manager.id, body="New reply", message_type="text",
                        ), send_to_telegram=False, pause_funnel_after_delivery=True)
                    audits = (await db.execute(select(AuditLog).where(AuditLog.action == AuditAction.CHAT_FUNNEL_PAUSED))).scalars().all()
                    assert len(audits) == 2
                for chat in chats[2:]:
                    assert not await FunnelRuntimeService(db).pause_for_manager_takeover(
                        chat_id=chat.id, project_id=project.id, actor=admin,
                    )
                await db.commit()
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()

    asyncio.run(run())
