from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.core.arq_queues import BACKUP_QUEUE_NAME, JOBS_QUEUE_NAME
from app.services.server_log_service import _redact
from app.workers.backup_worker import WorkerSettings as BackupWorkerSettings
from app.workers.postback_worker import WorkerSettings as JobsWorkerSettings


class ArqQueueIsolationTests(unittest.TestCase):
    def test_workers_listen_on_different_queues(self) -> None:
        self.assertEqual(JobsWorkerSettings.queue_name, JOBS_QUEUE_NAME)
        self.assertEqual(BackupWorkerSettings.queue_name, BACKUP_QUEUE_NAME)
        self.assertNotEqual(JobsWorkerSettings.queue_name, BackupWorkerSettings.queue_name)

    def test_every_enqueue_job_call_selects_a_queue(self) -> None:
        app_root = Path(__file__).resolve().parents[1] / "app"
        calls_without_queue: list[str] = []
        enqueue_calls = 0
        for path in app_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute) or node.func.attr != "enqueue_job":
                    continue
                enqueue_calls += 1
                if not any(keyword.arg == "_queue_name" for keyword in node.keywords):
                    calls_without_queue.append(f"{path.relative_to(app_root.parent)}:{node.lineno}")

        self.assertGreater(enqueue_calls, 0)
        self.assertEqual(calls_without_queue, [])

    def test_telegram_token_is_redacted_inside_bot_api_url(self) -> None:
        token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"
        redacted = _redact(f"POST https://api.telegram.org/bot{token}/sendMessage")
        self.assertNotIn(token, redacted)
        self.assertIn("[REDACTED_BOT_TOKEN]", redacted)


if __name__ == "__main__":
    unittest.main()
