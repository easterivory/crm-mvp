# Server restart preparation

## Deployment

Use the existing Compose project name, working directory, .env and all existing
override files (including the local backup Bot API override). Changing the project
name can select different empty volumes. Never use `down -v` for an update/reboot.

1. Take a PostgreSQL backup; preserve .env/encryption keys and persistent volumes.
   A SQL backup alone does not contain Redis, attachments or host proxy settings.
2. Choose a short maintenance window. Stop API and consumers before replacing
   Redis: api, worker, jobs, exports, backup, mtproto, plus any separately deployed
   consumers. This briefly makes CRM and landing endpoints unavailable. Allow
   active deliveries to settle before stopping when possible.
3. Gracefully stop Redis so its latest in-memory queue is written to disk:
   `docker compose stop -t 60 redis`. Check that shutdown completed normally; do
   not force-kill Redis during the first persistence upgrade.
4. Deploy the new files and rebuild application images. Start Redis with
   `docker compose up -d redis`. The mounted `docker/redis-start.sh` is required.
   A legacy RDB is converted on a loopback-only temporary port before the regular
   service opens port 6379. Conversion can take longer than the healthcheck window;
   wait for successful startup, do not delete persistence files to bypass errors.
5. Confirm `CONFIG GET appendonly appendfsync` reports `yes` and `everysec`, and
   INFO persistence reports successful AOF writes. Apply any pending application
   migrations before starting consumers. This patch adds no database migration;
   the prior broadcast patch requires revision `20261028_0089`.
6. Start the application services with the same Compose overrides as previously.
   Do not mix old and new scheduled-message workers during deployment.
7. Run `bash scripts/check-restart-readiness.sh` with the same Compose options.
   Check host Docker and Nginx/Caddy boot startup. This script only reads state;
   missing host settings must be corrected on the server by the operator.
8. Verify CRM and a landing through public HTTPS, a test /start, a reply continuing
   a funnel, an MTProto connection, and a scheduled test message. Check the
   scheduled-message list for interrupted deliveries before resending anything.

The commands above omit optional Compose flags for readability. Preserve them in
every command if used by the deployment. No server reboot or deployment is
performed by these repository changes.

## Recovery semantics

- PostgreSQL and media remain in existing persistent volumes.
- Redis now uses AOF with fsync every second. Abrupt power loss can still lose
  approximately the latest second of queue changes. AOF is not an external backup.
- The initial upgrade can preserve only data present in Redis's saved snapshot;
  graceful shutdown before recreation is essential. A conversion marker permits
  retrying an interrupted bootstrap from its original snapshot.
- Scheduled operator messages in `pending` remain eligible for normal delivery.
  A PostgreSQL advisory lock permits only one scheduled-message worker at a time.
  Under that lock, abandoned `running` items become `failed` with an explicit
  unknown-delivery explanation, visible in the existing scheduled-message UI.
  They are never automatically resent. Attachments are retained for inspection.
  `sent`, `cancelled` and existing `failed` records are unchanged.
- The lock requires a session-persistent PostgreSQL connection, not a
  transaction-pooling PgBouncer connection. It is released on process/connection
  termination; the next worker performs recovery.
- Funnel timers/state are not reset. Existing stale-job recovery is retained
  (default 900 seconds, bounded retries). It does not guarantee exactly-once
  external delivery across a crash. MTProto command recovery also retains its
  existing behavior; this patch does not redesign it.
- Broadcast recovery remains as documented in broadcast-throughput.md. Old failed
  recipients are not replayed. Reboot does not publish new funnel versions.
- Restart policies require the Docker daemon to start with the host. A manually
  stopped `unless-stopped` container must be started explicitly. Compose health
  dependencies are not a guarantee of host-reboot ordering.
- A 60-second container stop grace period allows cooperative shutdown, but does
  not make every Python task drain gracefully. In-flight network deliveries can
  still have an unknown outcome; consult recovery errors rather than resending
  them automatically.

Before a planned reboot, verify services are running and no large sends/backups
are underway. After reboot repeat the readiness checks and the test chat flow.
