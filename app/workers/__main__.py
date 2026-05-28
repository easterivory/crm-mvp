"""
Workers entrypoint — run via: python -m app.workers [alert|stats|funnel|broadcast|all]

Each worker is an independent asyncio loop.
Running 'all' starts both workers concurrently in the same process.

Usage:
    python -m app.workers alert   # alert worker only
    python -m app.workers stats   # stats worker only
    python -m app.workers funnel  # funnel scheduled jobs worker only
    python -m app.workers broadcast  # broadcast send worker only
    python -m app.workers all     # all workers (default in Docker)
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

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

    elif mode == "broadcast":
        from app.workers.broadcast_worker import run_loop
        asyncio.run(run_loop())

    elif mode == "all":
        from app.workers.alert_worker import run_loop as alert_loop
        from app.workers.broadcast_worker import run_loop as broadcast_loop
        from app.workers.funnel_scheduled_worker import run_loop as funnel_loop
        from app.workers.stats_worker import run_loop as stats_loop

        async def run_all() -> None:
            logger.info("Starting all workers")
            await asyncio.gather(
                alert_loop(),
                stats_loop(),
                funnel_loop(),
                broadcast_loop(),
            )

        asyncio.run(run_all())

    else:
        logger.error("Unknown worker mode: %r. Use: alert | stats | funnel | broadcast | all", mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
