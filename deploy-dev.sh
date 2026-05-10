#!/bin/bash
set -e

cd /opt/crm-mvp-dev

echo "=== Fetch dev branch ==="
git fetch origin

echo "=== Reset local dev to origin/dev ==="
git checkout dev
git reset --hard origin/dev

echo "=== Build and restart DEV containers ==="
docker compose --profile dev up -d --build

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
