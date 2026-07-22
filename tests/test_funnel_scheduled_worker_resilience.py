from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import httpx

from app.repositories.funnel_repository import FunnelRepository
from app.services import operational_alert_service
from app.services.funnel_runtime_service import (
    FunnelRuntimeDeliveryError,
    FunnelRuntimeService,
)
from app.services.operational_alert_service import OperationalAlertConfig
from app.services.telegram_sender import TelegramDeliveryError, TelegramSenderService
from app.workers import funnel_scheduled_worker


class _SessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class FunnelScheduledWorkerResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_job_executes_current_committed_step(self) -> None:
        chat_id = uuid4()
        funnel_version_id = uuid4()
        step_id = uuid4()
        step = SimpleNamespace(id=step_id)
        job = SimpleNamespace(
            id=uuid4(),
            chat_id=chat_id,
            funnel_version_id=funnel_version_id,
            step_id=step_id,
            job_type="resume_step",
        )
        service = FunnelRuntimeService.__new__(FunnelRuntimeService)
        service.repo = SimpleNamespace(
            get_chat_funnel_state=AsyncMock(
                return_value=SimpleNamespace(
                    completed_at=None,
                    is_paused=False,
                    funnel_version_id=funnel_version_id,
                    current_step_id=step_id,
                )
            ),
            get_step=AsyncMock(return_value=step),
        )
        service._execute_from_step = AsyncMock()

        await service.process_scheduled_job(job)

        service._execute_from_step.assert_awaited_once_with(
            chat_id=chat_id,
            step=step,
        )

    async def test_job_status_is_snapshotted_before_session_rollback(self) -> None:
        job_id = uuid4()
        db = MagicMock()
        db.rollback = AsyncMock()
        db.invalidate = AsyncMock()

        class RollbackSensitiveJob:
            @property
            def status(self) -> str:
                if db.rollback.await_count:
                    raise RuntimeError("expired ORM attribute was accessed")
                return "done"

        repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(return_value=RollbackSensitiveJob())
        )
        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=repo,
            ),
        ):
            status = await funnel_scheduled_worker._job_status(job_id)

        self.assertEqual(status, "done")
        db.rollback.assert_awaited_once()

    async def test_skipped_job_status_is_snapshotted_before_rollback(self) -> None:
        job_id = uuid4()
        db = MagicMock()
        db.rollback = AsyncMock()
        db.invalidate = AsyncMock()

        class RollbackSensitiveJob:
            @property
            def status(self) -> str:
                if db.rollback.await_count:
                    raise RuntimeError("expired ORM attribute was accessed")
                return "done"

        repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(return_value=RollbackSensitiveJob())
        )
        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=repo,
            ),
        ):
            result = await funnel_scheduled_worker._execute_claimed_job(job_id)

        self.assertEqual(
            result,
            {"status": "skipped", "job_id": str(job_id), "job_status": "done"},
        )
        db.rollback.assert_awaited_once()

    async def test_failed_runtime_rolls_back_and_persists_failure_in_fresh_session(self) -> None:
        job_id = uuid4()
        execution_db = MagicMock()
        execution_db.rollback = AsyncMock()
        execution_db.commit = AsyncMock()
        execution_db.invalidate = AsyncMock()
        failure_db = MagicMock()
        failure_db.rollback = AsyncMock()
        failure_db.commit = AsyncMock()
        failure_db.invalidate = AsyncMock()

        job = SimpleNamespace(id=job_id, status="running")
        execution_repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(return_value=job),
            mark_scheduled_job_done=AsyncMock(),
        )
        failure_repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(return_value=job),
            mark_scheduled_job_failed=AsyncMock(),
        )
        runtime = SimpleNamespace(
            process_scheduled_job=AsyncMock(
                side_effect=RuntimeError("connection is closed")
            )
        )

        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                side_effect=[
                    _SessionContext(execution_db),
                    _SessionContext(failure_db),
                ],
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                side_effect=[execution_repo, failure_repo],
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRuntimeService",
                return_value=runtime,
            ) as runtime_class,
            patch.object(
                funnel_scheduled_worker,
                "send_operational_alert",
                new=AsyncMock(return_value=True),
            ) as alert,
        ):
            result = await funnel_scheduled_worker._execute_claimed_job(job_id)

        self.assertEqual(result["status"], "failed")
        execution_db.rollback.assert_awaited_once()
        execution_db.commit.assert_not_awaited()
        failure_repo.mark_scheduled_job_failed.assert_awaited_once()
        failure_db.commit.assert_awaited_once()
        runtime_class.assert_called_once_with(
            execution_db,
            release_transaction_before_external_io=True,
            raise_on_telegram_delivery_error=True,
        )
        alert.assert_awaited_once()

    async def test_transient_delivery_retry_does_not_emit_final_failure_alert(self) -> None:
        job_id = uuid4()
        execution_db = MagicMock()
        execution_db.rollback = AsyncMock()
        execution_db.invalidate = AsyncMock()
        execution_repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(
                return_value=SimpleNamespace(id=job_id, status="running")
            )
        )
        error = TelegramDeliveryError(
            method="sendMessage",
            description="Network error (ReadTimeout)",
            transient=True,
        )
        runtime = SimpleNamespace(process_scheduled_job=AsyncMock(side_effect=error))

        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(execution_db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=execution_repo,
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRuntimeService",
                return_value=runtime,
            ),
            patch.object(
                funnel_scheduled_worker,
                "_resolve_delivery_failure",
                new=AsyncMock(
                    return_value={
                        "status": "retry_scheduled",
                        "attempts": 1,
                        "retry_in_seconds": 5,
                        "job_type": "message_sequence",
                        "step_id": str(uuid4()),
                        "failure_status_persisted": True,
                    }
                ),
            ),
            patch.object(
                funnel_scheduled_worker,
                "send_operational_alert",
                new=AsyncMock(),
            ) as alert,
        ):
            result = await funnel_scheduled_worker._execute_claimed_job(job_id)

        self.assertEqual(result["status"], "retry_scheduled")
        execution_db.rollback.assert_awaited_once()
        alert.assert_not_awaited()

    async def test_permanent_delivery_alert_contains_telegram_reason(self) -> None:
        job_id = uuid4()
        execution_db = MagicMock()
        execution_db.rollback = AsyncMock()
        execution_db.invalidate = AsyncMock()
        execution_repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(
                return_value=SimpleNamespace(id=job_id, status="running")
            )
        )
        error = TelegramDeliveryError(
            method="sendMessage",
            description="Bad Request: message is too long",
            status_code=400,
            error_code=400,
        )
        runtime = SimpleNamespace(process_scheduled_job=AsyncMock(side_effect=error))

        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(execution_db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=execution_repo,
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRuntimeService",
                return_value=runtime,
            ),
            patch.object(
                funnel_scheduled_worker,
                "_resolve_delivery_failure",
                new=AsyncMock(
                    return_value={
                        "status": "failed",
                        "attempts": 1,
                        "job_type": "message_sequence",
                        "step_id": str(uuid4()),
                        "failure_status_persisted": True,
                    }
                ),
            ),
            patch.object(
                funnel_scheduled_worker,
                "send_operational_alert",
                new=AsyncMock(return_value=True),
            ) as alert,
        ):
            result = await funnel_scheduled_worker._execute_claimed_job(job_id)

        self.assertEqual(result["status"], "failed")
        details = alert.await_args.kwargs["details"]
        self.assertEqual(details["telegram_http_status"], 400)
        self.assertEqual(
            details["telegram_description"],
            "Bad Request: message is too long",
        )

    async def test_run_once_continues_after_an_individual_job_failure(self) -> None:
        first_job_id = uuid4()
        second_job_id = uuid4()
        with (
            patch.object(
                funnel_scheduled_worker,
                "_recover_stale_jobs",
                new=AsyncMock(return_value=(0, 0)),
            ),
            patch.object(
                funnel_scheduled_worker,
                "_list_due_job_ids",
                new=AsyncMock(return_value=[first_job_id, second_job_id]),
            ),
            patch.object(
                funnel_scheduled_worker,
                "_claim_job",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                funnel_scheduled_worker,
                "_execute_claimed_job",
                new=AsyncMock(
                    side_effect=[
                        {"status": "failed", "job_id": str(first_job_id)},
                        {"status": "completed", "job_id": str(second_job_id)},
                    ]
                ),
            ) as execute,
        ):
            processed = await funnel_scheduled_worker.run_once(limit=2)

        self.assertEqual(processed, 1)
        self.assertEqual(
            execute.await_args_list,
            [call(first_job_id), call(second_job_id)],
        )

    async def test_transient_delivery_failure_requeues_exact_message_item(self) -> None:
        job_id = uuid4()
        chat_id = uuid4()
        funnel_version_id = uuid4()
        step_id = uuid4()
        db = MagicMock()
        db.rollback = AsyncMock()
        db.commit = AsyncMock()
        db.invalidate = AsyncMock()
        job = SimpleNamespace(
            id=job_id,
            status="running",
            attempts=1,
            chat_id=chat_id,
            funnel_version_id=funnel_version_id,
            step_id=step_id,
            job_type="delay_step",
            payload_json={},
        )
        state = SimpleNamespace(
            completed_at=None,
            is_paused=False,
            funnel_version_id=funnel_version_id,
            current_step_id=step_id,
        )
        repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(return_value=job),
            get_chat_funnel_state=AsyncMock(return_value=state),
            requeue_scheduled_job=AsyncMock(return_value=True),
        )
        telegram_error = TelegramDeliveryError(
            method="sendMessage",
            description="Too Many Requests: retry later",
            status_code=429,
            error_code=429,
            retry_after=12,
            transient=True,
        )
        runtime_error = FunnelRuntimeDeliveryError(
            telegram_error,
            retry_step_id=step_id,
            retry_job_type="message_sequence",
            retry_payload={"message_index": 3},
        )

        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=repo,
            ),
        ):
            result = await funnel_scheduled_worker._resolve_delivery_failure(
                job_id,
                runtime_error,
                str(runtime_error),
            )

        self.assertEqual(result["status"], "retry_scheduled")
        self.assertEqual(result["retry_in_seconds"], 12)
        requeue = repo.requeue_scheduled_job.await_args.kwargs
        self.assertEqual(requeue["job_type"], "message_sequence")
        self.assertEqual(requeue["step_id"], step_id)
        self.assertEqual(requeue["payload_json"], {"message_index": 3})
        db.commit.assert_awaited_once()

    async def test_transient_delivery_after_committed_transition_resumes_current_step(self) -> None:
        job_id = uuid4()
        chat_id = uuid4()
        funnel_version_id = uuid4()
        previous_step_id = uuid4()
        current_step_id = uuid4()
        db = MagicMock()
        db.rollback = AsyncMock()
        db.commit = AsyncMock()
        db.invalidate = AsyncMock()
        repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(
                return_value=SimpleNamespace(
                    status="running",
                    attempts=1,
                    chat_id=chat_id,
                    funnel_version_id=funnel_version_id,
                    step_id=previous_step_id,
                    job_type="delay_step",
                    payload_json={},
                )
            ),
            get_chat_funnel_state=AsyncMock(
                return_value=SimpleNamespace(
                    completed_at=None,
                    is_paused=False,
                    funnel_version_id=funnel_version_id,
                    current_step_id=current_step_id,
                )
            ),
            requeue_scheduled_job=AsyncMock(return_value=True),
        )
        error = TelegramDeliveryError(
            method="sendMessage",
            description="Network error (ConnectTimeout)",
            transient=True,
        )

        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=repo,
            ),
        ):
            result = await funnel_scheduled_worker._resolve_delivery_failure(
                job_id,
                error,
                str(error),
            )

        self.assertEqual(result["status"], "retry_scheduled")
        requeue = repo.requeue_scheduled_job.await_args.kwargs
        self.assertEqual(requeue["job_type"], "resume_step")
        self.assertEqual(requeue["step_id"], current_step_id)
        self.assertEqual(requeue["payload_json"], {})

    async def test_user_block_cancels_job_without_retry(self) -> None:
        job_id = uuid4()
        db = MagicMock()
        db.rollback = AsyncMock()
        db.commit = AsyncMock()
        db.invalidate = AsyncMock()
        repo = SimpleNamespace(
            get_scheduled_job=AsyncMock(
                return_value=SimpleNamespace(
                    status="running",
                    attempts=1,
                    chat_id=uuid4(),
                    funnel_version_id=uuid4(),
                    step_id=uuid4(),
                    job_type="message_sequence",
                    payload_json={"message_index": 0},
                )
            ),
            mark_scheduled_job_cancelled=AsyncMock(return_value=True),
        )
        error = TelegramDeliveryError(
            method="sendMessage",
            description="Forbidden: bot was blocked by the user",
            status_code=403,
            error_code=403,
            blocked=True,
        )

        with (
            patch.object(
                funnel_scheduled_worker,
                "get_db_session",
                return_value=_SessionContext(db),
            ),
            patch.object(
                funnel_scheduled_worker,
                "FunnelRepository",
                return_value=repo,
            ),
        ):
            result = await funnel_scheduled_worker._resolve_delivery_failure(
                job_id,
                error,
                str(error),
            )

        self.assertEqual(result["status"], "cancelled")
        repo.mark_scheduled_job_cancelled.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_stale_jobs_are_requeued_or_failed_by_attempt_count(self) -> None:
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    SimpleNamespace(rowcount=1),
                    SimpleNamespace(rowcount=2),
                ]
            )
        )
        repo = FunnelRepository(db)

        requeued, failed = await repo.recover_stale_running_jobs(
            stale_before=SimpleNamespace(),
            max_attempts=3,
        )

        self.assertEqual((requeued, failed), (2, 1))
        self.assertEqual(db.execute.await_count, 2)


class TelegramTransactionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_sender_commits_token_lookup_before_network(self) -> None:
        project_id = uuid4()
        bot_id = uuid4()
        db = MagicMock()
        db.in_transaction.return_value = True
        db.commit = AsyncMock()
        sender = TelegramSenderService(
            db,
            release_transaction_before_network=True,
        )
        sender.bot_repo = SimpleNamespace(
            get_bot_token_by_id=AsyncMock(return_value="telegram-token")
        )

        token = await sender._get_token(project_id, bot_id)

        self.assertEqual(token, "telegram-token")
        db.commit.assert_awaited_once()

    async def test_default_sender_keeps_existing_transaction_ownership(self) -> None:
        project_id = uuid4()
        bot_id = uuid4()
        db = MagicMock()
        db.in_transaction.return_value = True
        db.commit = AsyncMock()
        sender = TelegramSenderService(db)
        sender.bot_repo = SimpleNamespace(
            get_bot_token_by_id=AsyncMock(return_value="telegram-token")
        )

        token = await sender._get_token(project_id, bot_id)

        self.assertEqual(token, "telegram-token")
        db.commit.assert_not_awaited()

    async def test_default_sender_keeps_none_contract_for_telegram_failure(self) -> None:
        sender = TelegramSenderService(MagicMock())
        response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.telegram.org/bot-redacted/sendMessage"),
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry later",
                "parameters": {"retry_after": 9},
            },
        )

        result = await sender._result_or_delivery_error(
            method="sendMessage",
            response=response,
            project_id=uuid4(),
            bot_id=uuid4(),
            external_chat_id="123",
        )

        self.assertIsNone(result)

    async def test_strict_sender_exposes_safe_retry_metadata(self) -> None:
        sender = TelegramSenderService(MagicMock(), raise_on_delivery_error=True)
        response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.telegram.org/bot-secret/sendMessage"),
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry later",
                "parameters": {"retry_after": 9},
            },
        )

        with self.assertRaises(TelegramDeliveryError) as raised:
            await sender._result_or_delivery_error(
                method="sendMessage",
                response=response,
                project_id=uuid4(),
                bot_id=uuid4(),
                external_chat_id="123",
            )

        self.assertTrue(raised.exception.transient)
        self.assertEqual(raised.exception.retry_after, 9)
        self.assertNotIn("bot-secret", str(raised.exception))


class OperationalAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_delivery_releases_dedupe_slot_for_retry(self) -> None:
        with (
            patch.object(
                operational_alert_service,
                "_load_delivery_config",
                new=AsyncMock(
                    return_value=OperationalAlertConfig(
                        bot_token="backup-token",
                        chat_id="-100123",
                    )
                ),
            ),
            patch.object(
                operational_alert_service,
                "_reserve_alert_slot",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                operational_alert_service,
                "_release_alert_slot",
                new=AsyncMock(),
            ) as release,
            patch.object(
                operational_alert_service.asyncio,
                "to_thread",
                new=AsyncMock(side_effect=RuntimeError("telegram unavailable")),
            ),
        ):
            sent = await operational_alert_service.send_operational_alert(
                component="worker",
                title="failure",
                details={"job_id": uuid4()},
                dedupe_key="incident-key",
            )

        self.assertFalse(sent)
        release.assert_awaited_once_with("incident-key")
