"""Exercise deployment ordering with fake commands, never SSH/Docker/Git."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("failure", ["", "build", "backup", "migration"])
def test_deploy_never_starts_new_code_before_backup_and_migration(tmp_path, failure):
    root = tmp_path / "repo"
    (root / "frontend/dist/assets").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text('<div id="root"></div>')
    binaries = tmp_path / "bin"; binaries.mkdir()
    log = tmp_path / "commands.jsonl"
    docker = binaries / "docker"
    docker.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
a = sys.argv[1:]
with open(os.environ['COMMAND_LOG'], 'a') as f: f.write(json.dumps(a) + '\\n')
failure = os.environ.get('FAIL_PHASE')
phase = ('build' if 'build' in a else 'migration' if 'alembic' in a
         else 'backup' if any('pg_dump' in s for s in a) else '')
if failure and phase == failure: sys.exit(1)
if phase == 'backup': print('FAKE DATABASE BACKUP')
sys.exit(0)
''')
    docker.chmod(0o755)
    for name, body in {"git": "exit 0", "nginx": "exit 1", "find": "exit 0",
        "curl": "echo '<div id=\"root\"></div>'"}.items():
        executable = binaries / name
        executable.write_text("#!/bin/sh\n" + body + "\n"); executable.chmod(0o755)
    source = Path("deploy-dev.sh").read_text().replace("cd /opt/crm-mvp-dev", f'cd "{root}"', 1)
    script = tmp_path / "deploy-test.sh"; script.write_text(source)
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=20,
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "COMMAND_LOG": str(log),
             "FAIL_PHASE": failure, "BUILD_FRONTEND_ON_SERVER": "0"})
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    launches = [i for i, c in enumerate(commands) if "up" in c and "api" in c]
    migrations = [i for i, c in enumerate(commands) if "alembic" in c]
    backups = [i for i, c in enumerate(commands) if any("pg_dump" in a for a in c)]
    if failure:
        assert result.returncode != 0
        assert not launches
        if failure in {"build", "backup"}: assert not migrations
        if failure == "build": assert not any("stop" in c for c in commands)
    else:
        assert result.returncode == 0, result.stderr
        assert backups[0] < migrations[0] < launches[0]
        assert any("stop" in c and "mtproto" in c and "exports" in c for c in commands)
        dump = next((root / "backups/deploy").glob("*.dump"))
        assert dump.stat().st_mode & 0o777 == 0o600
        assert dump.read_text().strip() == "FAKE DATABASE BACKUP"
