from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.repositories.chat_repository import ChatRepository


def test_creation_and_activity_ranges_are_independent():
    engine = create_engine("sqlite:///:memory:")
    Chat.__table__.create(engine)
    def day(value):
        return datetime(2026, 9, value, tzinfo=timezone.utc)
    try:
        with Session(engine) as db:
            project_id = uuid4()
            ids = [uuid4() for _ in range(4)]
            for index, (created, active) in enumerate([(24, 27), (23, 24), (25, 25), (24, 24)]):
                db.add(Chat(id=ids[index], project_id=project_id, external_chat_id=str(index),
                            external_user_id=str(index),
                            created_at=day(created), last_message_at=day(active)))
            db.commit()
            repo = ChatRepository(db)
            def matches(**dates):
                stmt = repo._apply_filters(select(Chat.id), only_unread=False,
                    only_unanswered=False, only_red=False, only_hot_lead=False,
                    sla_threshold_minutes=30, manager_id=None, assigned_user_id=None,
                    unassigned=False, search_query=None, tracking_link_id=None,
                    tag_ids=(), tag_mode="any", lead_statuses=(), funnel_state=None,
                    **{"date_from": None, "date_to": None, **dates})
                return set(db.scalars(stmt).all())
            assert matches(date_from=day(24), date_to=day(25)) == {ids[0], ids[3]}
            assert matches(activity_from=day(24), activity_to=day(25)) == {ids[1], ids[3]}
            assert matches(date_from=day(24), date_to=day(25), activity_from=day(24), activity_to=day(25)) == {ids[3]}
            assert matches(date_from=day(25)) == {ids[2]}
            assert matches(date_to=day(24)) == {ids[1]}
            assert matches() == set(ids)
    finally:
        engine.dispose()
