#!/bin/bash
# Local deploy script - triggers deploy on remote server via SSH
# Usage: ./deploy-local.sh

set -euo pipefail

SERVER_USER="codex"
SERVER_HOST="45.59.113.248"
DEPLOY_PATH="/opt/crm-mvp-dev"

echo "🚀 Starting deployment to $SERVER_HOST..."
echo ""

# Check SSH connection
echo "📡 Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 "$SERVER_USER@$SERVER_HOST" "echo 'SSH connection OK'"; then
    echo "❌ SSH connection failed. Check your SSH key and server access."
    exit 1
fi
echo "✅ SSH connection successful"
echo ""

# Run deploy script on server
echo "🔄 Running deploy script on server..."
ssh "$SERVER_USER@$SERVER_HOST" "cd $DEPLOY_PATH && ./deploy-dev.sh"

echo ""
echo "✅ Deployment completed!"
echo ""
echo "🌐 Check your site:"
echo "   Frontend: http://sfera.cyou"
echo "   API Health: http://sfera.cyou/health"
echo "   API Docs: http://sfera.cyou/api/docs"
