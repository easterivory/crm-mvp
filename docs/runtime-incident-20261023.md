# Funnel incident: 23 October 2026

## Confirmed findings

- PostgreSQL reported `DiskFullError` while resizing `/PostgreSQL.*` shared-memory segments. Free space on the host filesystem does not establish free space in the database container's `/dev/shm`.
- Duplicate identity searches used a cross-table OR and loaded full duplicate details when scoring needed only a count. The new queries use separate indexed identity branches and deduplicate their union. Matching rules and visibility remain unchanged.
- Resource failures in duplicate checks could invalidate the surrounding funnel transaction. A savepoint now contains recognized resource failures; the previous confidence score is retained and marked deferred. Auto-submission remains prohibited until a successful recalculation.
- Recovery of some unstarted funnels passed a public message DTO without the internal repeated-start flag. Recovery now uses the persisted message. Repeated-start, mandatory-answer and 30-day inactivity policies remain unchanged.
- Persisting a Telegram block from a second database session could wait for the sending transaction's own chat lock. The independent writer now skips locked rows and defers persistence to the existing jobs queue. Timestamp ordering prevents an old queued block from overriding a newer unblock or incoming message.
- `VOICE_MESSAGES_FORBIDDEN` interrupted delivery to Telegram ID 1867667105. Bot automation now retries this definite rejection as ordinary video (video notes) or document (voice). Other failures, including timeouts, do not trigger this conversion. Manager sends retain their existing behavior. File-ID conversion requires a downloadable file within Telegram's 20 MB download limit; otherwise the error remains visible rather than silently skipping content.

The screenshot with the answer "Да" does not have a definitive matching delivery exception in the supplied log. Do not describe its individual cause as proven. The subsequent manager response intentionally paused that funnel.

## Deployment

1. Create and verify a current backup. Schedule a short maintenance window for database container recreation. Stop API and automation consumers during the transition; otherwise old and new processes can race.
2. Build the updated application image. Set `POSTGRES_SHM_SIZE=256m` (the compose default). This is a ceiling, not reserved memory; actual shared memory still counts against available host RAM.
3. Recreate only the PostgreSQL service with the updated compose configuration, retaining `postgres_data`. Never use `down -v`. Wait for database health before migrations or application startup.
4. Run `alembic upgrade head` from the new application image. Revision `20261023_0087` adds nullable `chats.telegram_block_state_at`, without rewriting existing values. It has a five-second lock timeout: on contention, resolve the blocking transaction and retry, rather than starting the new code against the old schema.
5. Recreate all application consumers from the same image, including `api`, `worker` and `jobs`. The jobs worker must register `persist_telegram_block_task`; do not deploy only the API.
6. Verify container `/dev/shm` size and free space, database health and queue processing. Check logs for `DiskFullError`, database deadlocks, start-recovery errors and deferred block task failures. Test a fresh bot start and a normal reply; verify a voice-restricted test account receives the ordinary-video fallback.

No automatic bulk replay of previously failed Telegram sends is included: network side effects may already have occurred, and some chats have since been taken over by managers. Those dialogs must be inspected before any selective recovery.

The host disk growth from 25 to 34 GB cannot be attributed from these application logs. Separately inspect database size, WAL retention, Docker logs, backups and attachment volumes before deleting anything. Increasing `/dev/shm` does not clean disk space or replace that audit.
