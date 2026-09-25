import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy.dialects import sqlite, postgresql

from app.models.chat import Chat
from app.services.lead_identity_service import LeadIdentityService


@pytest.mark.parametrize("scope,expected", [("all", 2), ("one", 1), ("none", 0)])
def test_duplicate_dialog_details_respect_project_visibility(scope, expected):
    source, p1, p2 = uuid4(), uuid4(), uuid4()
    visible = None if scope == "all" else [p1] if scope == "one" else []
    statement = LeadIdentityService._duplicate_rows_query(source, [Chat.external_user_id == "123456"], visible)
    assert "telegram_token" not in str(statement.compile(dialect=postgresql.dialect()))
    sql = str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
          CREATE TABLE projects (id TEXT, name TEXT);
          CREATE TABLE bots (id TEXT, name TEXT, bot_username TEXT, transport_type TEXT);
          CREATE TABLE chats (id TEXT, bot_id TEXT, external_user_id TEXT, is_deleted BOOLEAN);
          CREATE TABLE lead_statuses (id TEXT, code TEXT, name TEXT);
          CREATE TABLE leads (id TEXT, project_id TEXT, chat_id TEXT, status_id TEXT, name TEXT,
            phone TEXT, username TEXT, created_at TEXT, is_trash BOOLEAN, is_deleted BOOLEAN);
        """)
        status = uuid4().hex
        db.execute("INSERT INTO lead_statuses VALUES (?,?,?)", (status, "new", "New"))
        for project in [p1, p2]:
            chat, bot = uuid4().hex, uuid4().hex
            db.execute("INSERT INTO projects VALUES (?,?)", (project.hex, "Project"))
            db.execute("INSERT INTO bots VALUES (?,?,?,?)", (bot, "Account", "work_account", "user_mtproto"))
            db.execute("INSERT INTO chats VALUES (?,?,?,?)", (chat, bot, "123456", False))
            db.execute("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?)", (uuid4().hex, project.hex, chat, status, "Lead", None, "client_name", "2026-09-24", False, False))
            # Source lead must never be returned as its own duplicate.
            if project == p1:
                db.execute("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?)", (source.hex, project.hex, chat, status, "Source", None, "client_name", "2026-09-24", False, False))
        rows = db.execute(sql).fetchall()
        assert len(rows) == expected
        for row in rows:
            assert row["lead_id"] != source.hex
            assert row["chat_id"]
            assert row["external_user_id"] == "123456"
            assert row["bot_username"] == "work_account"
            assert row["transport_type"] == "user_mtproto"
            assert row["username"] == "client_name"
    finally:
        db.close()
