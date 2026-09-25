import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.backup_service import _telegram_method_url
from app.workers.backup_worker import WorkerSettings


def test_cloud_backup_defaults_unchanged():
    config = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://localhost/test", SECRET_KEY="test")
    assert config.BACKUP_TELEGRAM_MAX_UPLOAD_MB == 49
    assert _telegram_method_url("sendDocument", config, "123:test") == "https://api.telegram.org/bot123:test/sendDocument"


def test_backup_endpoint_override_is_scoped():
    config = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://localhost/test", SECRET_KEY="test",
                      BACKUP_TELEGRAM_API_BASE_URL="http://backup-telegram-api:8081/",
                      BACKUP_TELEGRAM_MAX_UPLOAD_MB=2000)
    assert _telegram_method_url("sendDocument", config, "123:test") == "http://backup-telegram-api:8081/bot123:test/sendDocument"
    assert config.BACKUP_TELEGRAM_MAX_UPLOAD_MB == 2000
    assert WorkerSettings.max_jobs == 1
    assert WorkerSettings.job_timeout > 300


@pytest.mark.skipif(not shutil.which("docker"), reason="Docker Compose CLI required")
def test_compose_override_keeps_credentials_and_routing_scoped():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, BACKUP_LOCAL_API_ID="12345", BACKUP_LOCAL_API_HASH="configuration-check")
    result = subprocess.run(
        ["docker", "compose", "--env-file", ".env.example", "-f", "docker-compose.yml", "-f",
         "docker-compose.backup-local-api.yml", "config", "--format", "json", "--no-env-resolution"],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    config = json.loads(result.stdout)
    local = config["services"]["backup-telegram-api"]
    assert not local.get("ports")
    assert "@sha256:" in local["image"]
    assert local["environment"]["TELEGRAM_LOCAL"] == "1"
    assert local["volumes"][0]["target"] == "/var/lib/telegram-bot-api"
    for name in ("api", "worker", "jobs", "mtproto", "backup"):
        overrides = config["services"][name]["environment"]
        assert overrides["BACKUP_TELEGRAM_API_BASE_URL"] == "http://backup-telegram-api:8081"
        assert overrides["APP_SERVICE_NAME"] == name
        assert "TELEGRAM_API_ID" not in overrides
        assert "TELEGRAM_API_BASE_URL" not in overrides
    assert config["services"]["backup"]["depends_on"]["redis"]["condition"] == "service_healthy"
