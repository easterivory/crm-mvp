from datetime import date
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.repositories.tracking_metrics_repository import TrackingMetricsRepository


@pytest.mark.parametrize("scenario,expected", [
    ("normal", 1), ("duplicate_join", 1), ("wrong_tag", 0), ("wrong_project", 0),
    ("wrong_buyer", 0), ("wrong_bot", 0), ("wrong_link", 0), ("deleted", 0),
    ("reset", 0), ("new_cycle", 1), ("outside_period", 0),
    ("unattributed_admin", 1), ("unattributed_buyer", 0),
])
def test_tag_graph_counts_distinct_current_cohort_and_scopes(scenario, expected):
    project, bot, buyer, link, tag, lead, chat = [uuid4() for _ in range(7)]
    statement = TrackingMetricsRepository.tagged_leads_query(
        project_id=project, tag_id=tag, date_from=date(2026, 9, 20), date_to=date(2026, 9, 25),
        bot_id=bot, buyer_id=None if scenario == "unattributed_admin" else buyer,
        link_id=link if scenario == "wrong_link" else None)
    assert "timezone" in str(statement.compile(dialect=postgresql.dialect()))
    db = sqlite3.connect(":memory:")
    db.create_function("timezone", 2, lambda zone, value: value)
    try:
        db.executescript("""
            CREATE TABLE leads (id TEXT, project_id TEXT, chat_id TEXT, created_at TEXT, is_deleted BOOLEAN);
            CREATE TABLE chats (id TEXT, bot_id TEXT, tracking_link_id TEXT, current_cycle_started_at TEXT,
                is_deleted BOOLEAN, reset_at TEXT);
            CREATE TABLE lead_tags (lead_id TEXT, tag_id TEXT);
            CREATE TABLE tracking_links (id TEXT, buyer_id TEXT, project_id TEXT);
        """)
        actual_link = uuid4().hex if scenario == "wrong_link" else link.hex
        db.execute("INSERT INTO tracking_links VALUES (?,?,?)", (actual_link, uuid4().hex if scenario == "wrong_buyer" else buyer.hex, project.hex))
        db.execute("INSERT INTO chats VALUES (?,?,?,?,?,?)", (
            chat.hex, uuid4().hex if scenario == "wrong_bot" else bot.hex,
            None if scenario.startswith("unattributed") else actual_link,
            "2026-09-24 12:00:00" if scenario == "new_cycle" else None, False,
            "2026-09-24" if scenario == "reset" else None))
        db.execute("INSERT INTO leads VALUES (?,?,?,?,?)", (
            lead.hex, uuid4().hex if scenario == "wrong_project" else project.hex, chat.hex,
            "2026-09-01 12:00:00" if scenario in {"new_cycle", "outside_period"} else "2026-09-24 12:00:00",
            scenario == "deleted"))
        db.execute("INSERT INTO lead_tags VALUES (?,?)", (lead.hex, uuid4().hex if scenario == "wrong_tag" else tag.hex))
        if scenario == "duplicate_join":
            db.execute("INSERT INTO lead_tags VALUES (?,?)", (lead.hex, tag.hex))
        sql = str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        rows = db.execute(sql).fetchall()
        assert sum(row[1] for row in rows) == expected
        if expected:
            assert rows[0][0] == "2026-09-24"
    finally:
        db.close()
