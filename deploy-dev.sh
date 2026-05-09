#!/bin/bash
set -e

cd /opt/crm-mvp-dev

echo "=== Fetch dev branch ==="
git fetch origin

echo "=== Reset local dev to origin/dev ==="
git checkout dev
git reset --hard origin/dev

echo "=== Build and restart DEV containers ==="
docker compose up -d --build

echo "=== Run migrations ==="
docker compose exec -T api alembic upgrade head

echo "=== Health check ==="
sleep 3
curl -fsS http://localhost:8001/health

echo ""
echo "=== DEV status ==="
docker compose ps
