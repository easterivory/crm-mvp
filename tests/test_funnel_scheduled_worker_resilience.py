from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

from app.repositories.funnel_repository import FunnelRepository
from app.services import operational_alert_service
from app.services.operational_alert_service import OperationalAlertConfig
from app.services.telegram_sender import TelegramSenderService
from app.workers import funnel_scheduled_worker


class _SessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class FunnelScheduledWorkerResilienceTests(unittest.IsolatedAsyncioTestCase):
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
        )
        alert.assert_awaited_once()

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
