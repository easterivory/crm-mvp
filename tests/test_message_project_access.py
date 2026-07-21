from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.constants import RoleName
from app.services.message_service import MessageService


def _operator(*, primary_project_id, extra_project_ids=()):
    return SimpleNamespace(
        is_deleted=False,
        role_name=RoleName.MANAGER,
        project_id=primary_project_id,
        project_accesses=[
            SimpleNamespace(project_id=project_id)
            for project_id in extra_project_ids
        ],
    )


def test_manager_can_send_in_additional_project() -> None:
    primary_project_id = uuid4()
    additional_project_id = uuid4()
    service = MessageService.__new__(MessageService)
    service.user_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=_operator(
                primary_project_id=primary_project_id,
                extra_project_ids=(additional_project_id,),
            )
        )
    )

    asyncio.run(
        service._ensure_operator_can_send(uuid4(), additional_project_id)
    )


def test_manager_cannot_send_without_project_access() -> None:
    service = MessageService.__new__(MessageService)
    service.user_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=_operator(primary_project_id=uuid4()))
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service._ensure_operator_can_send(uuid4(), uuid4()))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator is not a member of this project"


def test_super_admin_can_send_in_any_project() -> None:
    service = MessageService.__new__(MessageService)
    service.user_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                is_deleted=False,
                role_name=RoleName.SUPER_ADMIN,
                project_id=None,
                project_accesses=[],
            )
        )
    )

    asyncio.run(service._ensure_operator_can_send(uuid4(), uuid4()))
