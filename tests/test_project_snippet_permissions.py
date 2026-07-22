from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.core.constants import RoleName
from app.services.project_snippet_service import ProjectSnippetService


class ProjectSnippetDeletePermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_can_delete_project_snippet(self) -> None:
        project_id = uuid4()
        snippet_id = uuid4()
        service = ProjectSnippetService.__new__(ProjectSnippetService)
        service._ensure_access = AsyncMock()
        service.snippet_repo = SimpleNamespace(
            get_in_project=AsyncMock(
                return_value=SimpleNamespace(id=snippet_id, storage_path=None),
            ),
            delete_in_project=AsyncMock(return_value=True),
        )
        actor = SimpleNamespace(id=uuid4(), role_name=RoleName.ADMIN)

        await service.delete_snippet(
            project_id=project_id,
            snippet_id=snippet_id,
            actor=actor,
        )

        service._ensure_access.assert_awaited_once_with(project_id, actor)
        service.snippet_repo.delete_in_project.assert_awaited_once_with(snippet_id, project_id)

    async def test_manager_cannot_delete_project_snippet(self) -> None:
        service = ProjectSnippetService.__new__(ProjectSnippetService)
        service._ensure_access = AsyncMock()
        service.snippet_repo = SimpleNamespace(
            get_in_project=AsyncMock(),
            delete_in_project=AsyncMock(),
        )

        with self.assertRaises(HTTPException) as raised:
            await service.delete_snippet(
                project_id=uuid4(),
                snippet_id=uuid4(),
                actor=SimpleNamespace(id=uuid4(), role_name=RoleName.MANAGER),
            )

        self.assertEqual(raised.exception.status_code, 403)
        service.snippet_repo.get_in_project.assert_not_awaited()
