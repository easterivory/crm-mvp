# Separate postback server only

This directory is a standalone deployment artifact, not a CRM service.
- Read README.md and ../docs/postback-relay-gateway-server.md before deployment.
- Deploy only this directory on the separate gateway host. Its build context is this directory.
- Never run the repository root compose, migrations, seed or deploy-dev.sh on this host.
- Never copy the CRM database, Redis credentials, bot tokens, CRM .env or session files here.
- Use compose.gateway.yml explicitly. Do not rename it docker-compose.yml in the main CRM checkout.
- Preserve the queue volume; never run down -v or silently delete pending/dead jobs.
- No real postbacks or customer data in deployment smoke tests without explicit approval.
