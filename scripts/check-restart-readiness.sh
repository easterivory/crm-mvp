#!/usr/bin/env bash
# Read-only checks. Pass the same -f / --project-name options as normal deployment.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose "$@")

echo '=== Host autostart ==='
if command -v systemctl >/dev/null 2>&1; then
    systemctl is-enabled docker || echo 'ATTENTION: Docker boot startup is not confirmed'
    for service in nginx caddy; do
        if systemctl cat "$service" >/dev/null 2>&1; then
            systemctl is-enabled "$service" || echo "ATTENTION: $service boot startup is not confirmed"
        fi
    done
else
    echo 'systemd unavailable; verify Docker and external proxy autostart on this host'
fi

echo '=== Containers and restart policies ==='
"${compose[@]}" ps -a
while IFS= read -r id; do
    [ -n "$id" ] || continue
    docker inspect --format '{{.Name}} status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}' "$id"
done < <("${compose[@]}" ps -aq)

echo '=== Redis durability ==='
"${compose[@]}" exec -T redis redis-cli PING
"${compose[@]}" exec -T redis redis-cli CONFIG GET appendonly appendfsync
"${compose[@]}" exec -T redis redis-cli INFO persistence | tr -d '\r' | grep -E '^(loading|aof_enabled|aof_last_write_status|aof_last_bgrewrite_status|aof_rewrite_in_progress|rdb_last_bgsave_status):'

echo '=== PostgreSQL and queue states ==='
"${compose[@]}" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${compose[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT status, count(*) FROM scheduled_messages GROUP BY status; SELECT status, count(*) FROM funnel_scheduled_jobs GROUP BY status;"'
echo 'Check public CRM/landing HTTPS and a test bot separately. No settings were changed.'
