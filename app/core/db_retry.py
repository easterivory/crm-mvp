"""Classify database failures without logging statements or customer parameters."""
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout


def sqlstate(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        value = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
        if value:
            return str(value)
        exc = getattr(exc, "orig", None) or getattr(exc, "__cause__", None)
    return None


def retryable_database_error(exc):
    if isinstance(exc, PoolTimeout):
        return True
    if not isinstance(exc, DBAPIError):
        return False
    state = sqlstate(exc)
    if state:
        return state in {"40001", "40P01", "55P03", "53300", "57P01", "57P02", "57P03"} or state.startswith("08")
    return bool(exc.connection_invalidated)


def failure_details(exc, *, committed=False, external_io_started=False):
    return {"error_type": type(exc).__name__, "sqlstate": sqlstate(exc),
            "field": getattr(exc, "field", None), "reason": getattr(exc, "code", None),
            "committed": committed, "external_io_started": external_io_started}
