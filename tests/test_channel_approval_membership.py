import pytest

from app.workers.postback_worker import _membership_is_active


@pytest.mark.parametrize("member,expected", [
    ({"status": "member"}, True),
    ({"status": "administrator"}, True),
    ({"status": "creator"}, True),
    ({"status": "restricted", "is_member": True}, True),
    ({"status": "restricted", "is_member": False}, False),
    ({"status": "left"}, False),
    ({"status": "kicked"}, False),
])
def test_membership_decision(member, expected):
    assert _membership_is_active(member) is expected


@pytest.mark.parametrize("member", [{}, {"status": "unknown"}, {"status": "restricted"}])
def test_unverifiable_membership_is_not_treated_as_success_or_absence(member):
    with pytest.raises(ValueError):
        _membership_is_active(member)
