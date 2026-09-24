"""Execute attribution selection against an isolated database, without service doubles."""
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy.dialects import sqlite, postgresql

from app.repositories.lead_repository import LeadRepository


@pytest.mark.parametrize("scenario,expected", [
    ("single", 1), ("repeated", 1), ("ambiguous", 2),
    ("prior_cycle", 0), ("other_project", 0), ("other_bot", 0),
    ("other_chat", 0), ("manager", 0), ("no_source", 0),
    ("legacy_cycle", 1),
])
def test_tracking_history_is_scoped_and_keeps_ambiguity(scenario, expected):
    lead, chat, project, bot, link = [uuid4() for _ in range(5)]
    query = LeadRepository._tracking_history_query(lead)
    sql = str(query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    # The same ORM query must also compile for the production database.
    assert "LIMIT" in str(query.compile(dialect=postgresql.dialect()))
    db = sqlite3.connect(":memory:")
    try:
        db.executescript("""
            CREATE TABLE leads (id TEXT, chat_id TEXT, project_id TEXT);
            CREATE TABLE chats (id TEXT, bot_id TEXT, current_cycle_started_at TEXT, created_at TEXT);
            CREATE TABLE messages (chat_id TEXT, tracking_link_id TEXT, sender_type TEXT, created_at TEXT);
            CREATE TABLE tracking_links (id TEXT, code TEXT, ref_code TEXT, title TEXT, project_id TEXT, bot_id TEXT);
        """)
        db.execute("INSERT INTO leads VALUES (?,?,?)", (lead.hex, chat.hex, project.hex))
        db.execute("INSERT INTO chats VALUES (?,?,?,?)", (chat.hex, bot.hex, None if scenario == "legacy_cycle" else "2026-09-20", "2026-09-01"))
        db.execute("INSERT INTO tracking_links VALUES (?,?,?,?,?,?)", (
            link.hex, "source", "ref", "Campaign", uuid4().hex if scenario == "other_project" else project.hex,
            uuid4().hex if scenario == "other_bot" else bot.hex,
        ))
        message = (uuid4().hex if scenario == "other_chat" else chat.hex,
                   None if scenario == "no_source" else link.hex,
                   "manager" if scenario == "manager" else "user",
                   "2026-09-10" if scenario in {"prior_cycle", "legacy_cycle"} else "2026-09-21")
        db.execute("INSERT INTO messages VALUES (?,?,?,?)", message)
        if scenario == "repeated":
            db.execute("INSERT INTO messages VALUES (?,?,?,?)", message)
        if scenario == "ambiguous":
            other = uuid4().hex
            db.execute("INSERT INTO tracking_links VALUES (?,?,?,?,?,?)", (other, "other", "ref2", "Other", project.hex, bot.hex))
            db.execute("INSERT INTO messages VALUES (?,?,?,?)", (chat.hex, other, "user", "2026-09-22"))
        assert len(db.execute(sql).fetchall()) == expected
    finally:
        db.close()
