# Deployment boundaries

The normal deployment target of this repository is the MAIN CRM server.

The optional `postback_gateway/` directory is a separate deployment artifact for a DIFFERENT host. It is excluded from the main Docker build and is deliberately absent from the root compose/deploy scripts.

For MAIN server work, read `docs/postback-relay-main-server.md`. Do not deploy `postback_gateway/compose.gateway.yml`, install its public nginx configuration, create its queue volume or open its public port on the main server.

For a task explicitly targeting the SEPARATE POSTBACK server, read `docs/postback-relay-gateway-server.md` and `postback_gateway/AGENTS.md`. Do not run main CRM migrations/compose/seeds there. Never copy the CRM `.env`, database, Redis credentials, bot tokens or Telegram sessions to that host.

Both components are opt-in. Do not enable live traffic, rotate real endpoint secrets, disable old callback URLs or perform test conversions on real leads without explicit user authorization.
