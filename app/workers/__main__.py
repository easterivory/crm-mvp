"""
Workers entrypoint — run via: python -m app.workers [alert|stats|funnel|broadcast|scheduled|postback|buyer|admin|backup|mtproto|all]

Each worker is an independent asyncio loop.
Running 'all' starts both workers concurrently in the same process.

Usage:
    python -m app.workers alert   # alert worker only
    python -m app.workers stats   # stats worker only
    python -m app.workers funnel  # funnel scheduled jobs worker only
    python -m app.workers broadcast  # broadcast send worker only
    python -m app.workers postback  # partner postback worker only
    python -m app.workers buyer  # buyer Telegram bot polling worker only
    python -m app.workers backup  # scheduled database backups only
    python -m app.workers mtproto # dedicated Telegram work-account process
    python -m app.workers all     # shared workers (default in Docker)
"""
import asyncio
import logging
import sys

from app.core.logging_config import configure_file_logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
configure_file_logging()

logger = logging.getLogger(__name__)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "alert":
        from app.workers.alert_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "stats":
        from app.workers.stats_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "funnel":
        from app.workers.funnel_scheduled_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "push":
        from app.workers.funnel_push_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "broadcast":
        from app.workers.broadcast_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "scheduled":
        from app.workers.scheduled_message_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "postback":
        from app.workers.postback_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "buyer":
        from app.workers.buyer_bot import run_loop
        asyncio.run(run_loop())

    elif mode == "admin":
        from app.workers.admin_bot import run_loop
        asyncio.run(run_loop())

    elif mode == "backup":
        from app.workers.backup_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "mtproto":
        from app.workers.telegram_account_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "all":
        from app.workers.alert_worker import run_loop as alert_loop
        from app.workers.broadcast_worker import run_loop as broadcast_loop
        from app.workers.buyer_bot import run_loop as buyer_loop
        from app.workers.admin_bot import run_loop as admin_loop
        from app.workers.funnel_scheduled_worker import run_loop as funnel_loop
        from app.workers.funnel_push_worker import run_loop as push_loop
        from app.workers.postback_worker import run_loop as postback_loop
        from app.workers.scheduled_message_worker import run_loop as scheduled_loop
        from app.workers.stats_worker import run_loop as stats_loop

        async def run_all() -> None:
            logger.info("Starting shared workers; MTProto runs in its dedicated service")
            await asyncio.gather(
                alert_loop(),
                stats_loop(),
                funnel_loop(),
                push_loop(),
                broadcast_loop(),
                scheduled_loop(),
                postback_loop(),
                buyer_loop(),
                admin_loop(),
            )

        asyncio.run(run_all())

    else:
        logger.error(
            "Unknown worker mode: %r. Use: alert | stats | funnel | push | broadcast | scheduled | postback | buyer | admin | backup | mtproto | all",
            mode,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
