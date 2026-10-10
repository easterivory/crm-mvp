import asyncio

from arq import cron
from arq.connections import RedisSettings

from app.core.arq_queues import DIALOG_EXPORT_QUEUE_NAME
from app.core.config import settings
from app.core.logging_config import configure_file_logging
from app.services.dialog_export_files import cleanup_exports
from app.services.dialog_export_service import run_dialog_export

configure_file_logging()


async def cleanup_dialog_exports(ctx):
    await asyncio.to_thread(cleanup_exports)


class WorkerSettings:
    functions = [run_dialog_export]
    cron_jobs = [cron(cleanup_dialog_exports, minute=0, run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    queue_name = DIALOG_EXPORT_QUEUE_NAME
    max_jobs = 1
    job_timeout = 3600
    health_check_interval = 30
    max_tries = 1
