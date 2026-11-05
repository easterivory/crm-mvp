"""Track a possible external side effect while handling a durable update."""
from contextvars import ContextVar

delivery_attempt: ContextVar[dict | None] = ContextVar("telegram_delivery_attempt", default=None)


def note_external_delivery() -> None:
    progress = delivery_attempt.get()
    if progress is not None:
        progress["external_io_started"] = True
