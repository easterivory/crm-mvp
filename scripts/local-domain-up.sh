#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${LOCAL_DOMAIN:-adswiftly.pro}"
HOST_ALIASES="${LOCAL_DOMAIN_ALIASES:-www.${DOMAIN}}"
PROXY_PORT="${LOCAL_PROXY_PORT:-80}"
API_PORT="${API_PORT:-8000}"
HOSTS_MARKER_BEGIN="# crm-mvp local-domain begin"
HOSTS_MARKER_END="# crm-mvp local-domain end"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

compose() {
  docker compose -f docker-compose.yml -f docker-compose.local-domain.yml "$@"
}

ensure_hosts() {
  if [[ "${LOCAL_SKIP_HOSTS:-0}" == "1" ]]; then
    return
  fi

  if grep -Eq "^[[:space:]]*127\\.0\\.0\\.1[[:space:]].*(^|[[:space:]])${DOMAIN}([[:space:]]|$)" /etc/hosts; then
    return
  fi

  echo "Adding local hosts entry for ${DOMAIN}. macOS may ask for your password."
  {
    echo ""
    echo "$HOSTS_MARKER_BEGIN"
    echo "127.0.0.1 ${DOMAIN} ${HOST_ALIASES}"
    echo "::1 ${DOMAIN} ${HOST_ALIASES}"
    echo "$HOSTS_MARKER_END"
  } | sudo tee -a /etc/hosts >/dev/null
}

wait_for_api() {
  local url="http://127.0.0.1:${API_PORT}/health"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  echo "API did not become healthy at ${url}. Recent api logs:" >&2
  compose logs --tail=80 api >&2 || true
  exit 1
}

cd "$ROOT"

need curl
need docker
need npm

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop and run this script again." >&2
  exit 1
fi

ensure_hosts

if [[ "${LOCAL_SKIP_FRONTEND_BUILD:-0}" != "1" ]]; then
  echo "Building frontend from local files..."
  (
    cd "$ROOT/frontend"
    if [[ ! -d node_modules ]]; then
      npm ci --include=dev
    fi
    npm run build
  )
fi

echo "Starting PostgreSQL and Redis..."
compose up -d --build postgres redis

if [[ "${LOCAL_SKIP_BACKEND_BUILD:-0}" != "1" ]]; then
  echo "Building backend image from local files..."
  compose build api worker jobs
fi

if [[ "${LOCAL_SKIP_MIGRATIONS:-0}" != "1" ]]; then
  echo "Applying database migrations..."
  compose run --rm --no-deps api alembic upgrade head
fi

echo "Starting API, workers, and local domain proxy..."
export LOCAL_PROXY_PORT
compose up -d api worker jobs local_domain_proxy
wait_for_api

shown_port=""
if [[ "$PROXY_PORT" != "80" ]]; then
  shown_port=":${PROXY_PORT}"
fi

echo ""
echo "CRM is running locally:"
echo "  http://${DOMAIN}${shown_port}"
echo ""
echo "Stop it with:"
echo "  ./scripts/local-domain-down.sh"
