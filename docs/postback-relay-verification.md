# Postback relay: verification and release gate

Checked locally on 2026-11-03. No production deployment or live postbacks were performed.

## Passed

- `.venv/bin/python -m pytest -q`: 851 passed, 78 skipped, 7 subtests passed.
- Frontend TypeScript/Vite production build; generated frontend/dist updated.
- Native nginx configuration validation with a temporary certificate.
- Signature validation, disabled integration, wrong signatures and stale timestamps.
- Durable SQLite intake, restart/reclaim, bounded capacity, concurrent admission,
  expired/revoked manifest, malformed/oversized requests and unsupported formats.
- Delivery retries, lost/invalid acknowledgements, retained terminal failures,
  stable delivery IDs, local backup restoration and restrictive backup permissions.
- HTTP acknowledgement after commit; failed commit returns 503, not success.
- Deployment isolation: no gateway service in the main deployment, no imports
  from the CRM application in the standalone package.

## Not verified: required before production enablement

Docker Desktop's engine socket was unavailable. No containers were reset or
user volumes removed. The three PostgreSQL tests in tests/test_postback_relay.py
were skipped, not passed. Container image build/start was not verified either.

On a machine with a DISPOSABLE PostgreSQL database, run from the repository root:

```sh
CRM_TEST_POSTGRES_URL=postgresql+asyncpg://USER:PASSWORD@127.0.0.1:PORT/TEST_DATABASE .venv/bin/python -m pytest -q tests/test_postback_relay.py
```

Never supply production database credentials. These tests create and drop random
schemas and need schema creation rights. They exercise migration 0092, concurrent
duplicate delivery, business/receipt rollback, lost responses and project scope.

Also build/start the standalone container on a staging host and check readiness,
VPN/firewall boundaries, TLS, queue persistence across restart, backup restoration
and a synthetic conversion in a dedicated test project. Do not enable production
relay URLs until these checks pass. Unit tests do not prove production throughput
or DDoS resistance.

## Handoff boundaries

- Main CRM deployment: docs/postback-relay-main-server.md only.
- Separate gateway deployment: docs/postback-relay-gateway-server.md and
  postback_gateway/README.md. Do not deploy CRM/database services there.
- Integration is off by default; legacy direct callbacks stay enabled.
- Migration only adds the delivery ledger. Do not delete it or downgrade it:
  persisted IDs prevent reprocessing after retries or queue restoration.
- Partner retries arriving as NEW requests require a unique external event ID
  for business deduplication. Transport deduplication alone cannot identify them.
- Accepted events are queued; accepted does not mean matched to a lead yet.
  Monitor pending age and dead jobs, not just HTTP uptime.
