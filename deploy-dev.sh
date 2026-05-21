#!/bin/bash
set -euo pipefail

cd /opt/crm-mvp-dev

FRONTEND_DIR="$PWD/frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist"
FRONTEND_API_URL="${VITE_API_URL:-/api/v1}"
NODE_IMAGE="${NODE_IMAGE:-node:20-alpine}"
BUILD_FRONTEND_ON_SERVER="${BUILD_FRONTEND_ON_SERVER:-0}"

print_frontend_assets() {
  echo "Frontend dist path: $FRONTEND_DIST"
  if [ ! -f "$FRONTEND_DIST/index.html" ]; then
    echo "Frontend build did not produce $FRONTEND_DIST/index.html" >&2
    exit 1
  fi
  echo "Frontend assets:"
  find "$FRONTEND_DIST/assets" -maxdepth 1 -type f \( -name '*.js' -o -name '*.css' \) -printf '  %f\n' | sort
}

build_frontend_with_host_node() {
  echo "Frontend build mode: host Node/npm"
  echo "node: $(node -v)"
  echo "npm: $(npm -v)"
  (
    cd "$FRONTEND_DIR"
    npm ci --include=dev --no-audit --no-fund
    VITE_API_URL="$FRONTEND_API_URL" npm run build
  )
}

build_frontend_with_docker_node() {
  echo "Frontend build mode: Docker $NODE_IMAGE"
  docker run --rm "$NODE_IMAGE" sh -lc 'node -v && npm -v'
  docker run --rm \
    -e VITE_API_URL="$FRONTEND_API_URL" \
    -e npm_config_cache=/tmp/npm-cache \
    -v "$FRONTEND_DIR:/app" \
    -w /app \
    "$NODE_IMAGE" \
    sh -lc "npm ci --include=dev --no-audit --no-fund && npm run build && chown -R $(id -u):$(id -g) dist node_modules"
}

reload_nginx_if_present() {
  echo "=== Nginx refresh ==="
  if ! command -v nginx >/dev/null 2>&1; then
    echo "nginx binary not found; frontend files were updated in-place."
    return
  fi

  nginx -t
  if command -v systemctl >/dev/null 2>&1 && systemctl reload nginx; then
    echo "nginx reloaded via systemctl"
    return
  fi
  if nginx -s reload; then
    echo "nginx reloaded via nginx -s reload"
    return
  fi
  echo "nginx reload was not available; static files were updated in-place."
}

echo "=== Fetch dev branch ==="
git fetch origin

echo "=== Reset local dev to origin/dev ==="
git checkout dev
git reset --hard origin/dev

echo "=== Cleanup stale runtime containers ==="
docker rm -f crm_mvp_dev-frontend-1 2>/dev/null || true
docker compose rm -sf api worker

echo "=== Build and restart DEV containers ==="
docker compose up -d --build postgres redis api worker

echo "=== Frontend static assets ==="
if [ "$BUILD_FRONTEND_ON_SERVER" = "1" ]; then
  echo "VITE_API_URL=$FRONTEND_API_URL"
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    build_frontend_with_host_node
  else
    build_frontend_with_docker_node
  fi
else
  echo "Using committed frontend/dist assets. Set BUILD_FRONTEND_ON_SERVER=1 to rebuild on the server."
fi
print_frontend_assets
reload_nginx_if_present

echo "=== Run migrations ==="
docker compose exec -T api alembic upgrade head

echo "=== Seed dev users ==="
docker compose exec -T api python scripts/seed_test_users.py

echo "=== Seed dev Telegram bot if configured ==="
if docker compose exec -T api sh -c 'test -n "$TELEGRAM_BOT_TOKEN"'; then
  docker compose exec -T api python scripts/seed_test_bot.py
else
  echo "TELEGRAM_BOT_TOKEN is not set; skipping bot seed"
fi

echo "=== Health check ==="
sleep 3
curl -fsS http://localhost:8001/health

echo ""
echo "=== DEV status ==="
docker compose ps
