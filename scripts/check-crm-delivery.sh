#!/usr/bin/env bash
# Read-only MAIN server diagnostics. Supply the normal compose -f/project options.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose "$@")
echo '=== Effective backup-worker transport (no tokens) ==='
"${compose[@]}" exec -T backup python -c 'import json; from app.services.backup_diagnostics import transport_status; print(json.dumps(transport_status(), ensure_ascii=False))'
echo '=== Telegram DNS from worker ==='
"${compose[@]}" exec -T worker python -c 'import socket; result=socket.getaddrinfo("api.telegram.org",443,type=socket.SOCK_STREAM); print("DNS records:", len(result))' || echo 'ATTENTION: worker DNS lookup failed; queue checks continue'
echo '=== Durable queue states, read only ==='
"${compose[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
BEGIN READ ONLY;
SELECT status,count(*) FROM runtime_dispatches GROUP BY status;
SELECT id,kind,status,failure_count,diagnostics_json->>'sqlstate' AS sqlstate
FROM runtime_dispatches WHERE status='review' ORDER BY created_at LIMIT 100;
SELECT status,count(*) FROM advertising_deliveries GROUP BY status;
COMMIT;
SQL
echo 'No queues, bot settings, firewall rules or SSH settings were changed.'
