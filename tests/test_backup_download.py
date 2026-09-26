import asyncio
import os
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.dependencies import get_current_root_user
from app.api.v1.routers.settings import router
from app.core.config import Settings
from app.core.constants import ROOT_ADMIN_EMAIL
from app.models.user import User
from app.services.backup_download_service import (
    DOWNLOAD_TTL_SECONDS, cleanup_downloads, download_directory, resolve_download,
)
from app.workers.backup_worker import WorkerSettings


@pytest.fixture
def config(tmp_path):
    return Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://localhost/test",
                    SECRET_KEY="test", BACKUP_STORAGE_PATH=str(tmp_path))


@pytest.mark.parametrize("suffix", [".sql.gz", ".sql.gz.enc"])
def test_download_resolves_only_its_own_archive(config, suffix):
    identifier = uuid4()
    directory = download_directory(config)
    directory.mkdir()
    path = directory / f"download_{identifier}{suffix}"
    path.write_bytes(b"archive")
    assert resolve_download(identifier, path.name, config) == path
    with pytest.raises(ValueError):
        resolve_download(uuid4(), path.name, config)
    with pytest.raises(ValueError):
        resolve_download(identifier, "../" + path.name, config)


def test_expiry_and_cleanup_do_not_touch_regular_backups(config):
    directory = download_directory(config)
    directory.mkdir()
    identifier = uuid4()
    old = directory / f"download_{identifier}.sql.gz"
    fresh = directory / f"download_{uuid4()}.sql.gz"
    regular = directory.parent / "crm_mvp_old.sql.gz"
    for path in (old, fresh, regular):
        path.write_bytes(b"archive")
    earlier = time.time() - DOWNLOAD_TTL_SECONDS - 60
    os.utime(old, (earlier, earlier))
    os.utime(regular, (earlier, earlier))
    with pytest.raises(FileNotFoundError):
        resolve_download(identifier, old.name, config)
    cleanup_downloads(config)
    assert not old.exists()
    assert fresh.exists() and regular.exists()


def test_symlinks_rejected(config):
    directory = download_directory(config)
    directory.mkdir()
    target = directory.parent / "secret"
    target.write_text("secret")
    identifier = uuid4()
    link = directory / f"download_{identifier}.sql.gz"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        resolve_download(identifier, link.name, config)


def test_all_download_routes_require_root():
    routes = [route for route in router.routes if "/backup/download" in route.path]
    assert len(routes) == 3
    for route in routes:
        assert any(dep.call is get_current_root_user for dep in route.dependant.dependencies)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(get_current_root_user(User(email="manager@example.com")))
    assert denied.value.status_code == 403
    root = User(email=ROOT_ADMIN_EMAIL)
    assert asyncio.run(get_current_root_user(root)) is root


def test_download_job_registered_with_long_result_retention():
    jobs = [job for job in WorkerSettings.functions if getattr(job, "name", None) == "run_download_backup_job"]
    assert len(jobs) == 1
    assert jobs[0].keep_result_s == DOWNLOAD_TTL_SECONDS
