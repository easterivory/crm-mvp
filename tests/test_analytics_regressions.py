import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.services.manager_analytics_service import ManagerAnalyticsService


class _EmptyAnalyticsResult:
    class _Mappings:
        @staticmethod
        def all() -> list:
            return []

    def mappings(self) -> _Mappings:
        return self._Mappings()


def test_manager_funnel_metric_compiles_as_joined_completion_events() -> None:
    db = AsyncMock()
    db.execute.return_value = _EmptyAnalyticsResult()

    async def run():
        return await ManagerAnalyticsService(db).get_project_performance(
            project_id=uuid4(),
        )

    result = asyncio.run(run())
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert result == []
    assert "funnel_runtime_logs" in sql
    assert "chat_funnel_states" in sql
    assert "completed_at >=" in sql
