#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${LOCAL_DOMAIN:-adswiftly.pro}"
PROXY_PORT="${LOCAL_PROXY_PORT:-80}"
HOSTS_MARKER_BEGIN="# crm-mvp local-domain begin"
HOSTS_MARKER_END="# crm-mvp local-domain end"
RESTORE_DNS=0

for arg in "$@"; do
  case "$arg" in
    --restore-dns)
      RESTORE_DNS=1
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

compose() {
  docker compose -f docker-compose.yml -f docker-compose.local-domain.yml "$@"
}

restore_dns() {
  if [[ "$RESTORE_DNS" != "1" ]]; then
    return
  fi

  echo "Removing local hosts entry for ${DOMAIN}. macOS may ask for your password."
  local tmp_hosts
  tmp_hosts="$(mktemp)"
  awk -v begin="$HOSTS_MARKER_BEGIN" -v end="$HOSTS_MARKER_END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    skip != 1 { print }
  ' /etc/hosts >"$tmp_hosts"
  sudo cp "$tmp_hosts" /etc/hosts
  rm -f "$tmp_hosts"
}

cd "$ROOT"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  export LOCAL_PROXY_PORT
  compose stop local_domain_proxy api worker jobs backup postgres redis >/dev/null || true
fi

restore_dns

echo "Local CRM stack is stopped."
if [[ "$RESTORE_DNS" != "1" ]] && grep -Eq "^[[:space:]]*127\\.0\\.0\\.1[[:space:]].*(^|[[:space:]])${DOMAIN}([[:space:]]|$)" /etc/hosts; then
  echo "Hosts entry is kept for quick next start. Use --restore-dns to point ${DOMAIN} back to public DNS."
fi
