# Broadcast delivery, 2026-10-28

## Changes

Bot API campaigns use a run-scoped pooled HTTP client, bounded parallel recipient
delivery (one SQLAlchemy session per recipient), and a paced 20 requests/second
transport. Messages to the same chat are spaced by at least one second within a
campaign. The bot's other traffic is not counted by this limiter; the default
leaves headroom, and explicit Telegram 429 responses impose a common cooldown.
There is no paid-broadcast mode.

Uploads can reuse a successful Telegram file ID for subsequent recipients of the
same bot and media type during the run. Personal-account transports remain serial
and do not use the Bot API upload cache. No 1000/minute promise applies to MTProto.

A dedicated PostgreSQL connection holds a session advisory lock per bot, covering
both polling and ARQ workers and different campaigns for that bot. Do not put this
connection through transaction-pooling PgBouncer. Recipient claims are committed
before network delivery. An abandoned `sending` recipient becomes failed with an
unknown-outcome explanation on the next active run, rather than being resent.
Exactly-once Telegram delivery cannot be guaranteed across a network/process
failure. Already-failed recipients from older campaigns are not replayed.

Only explicit 429 rejections of replayable JSON/form requests retry automatically
(up to three attempts). Multipart uploads and unknown network outcomes are not
automatically replayed. Telegram error codes/descriptions are retained. A failure
after part of a multi-message campaign does not restart that recipient from the
first message. Pending counts include in-flight delivery.

Pause/cancel prevents new recipients starting; up to the configured concurrency
may already be in flight and finish. A recipient's configured sequence, delays,
buttons and after-send funnel action continue to run in order. Campaign totals
refresh after each batch. Batch logs include elapsed time, successes, failures and
concurrency. Different campaigns are still selected by the existing queue order.

## Deployment

1. Stop old broadcast consumers (including the jobs/ARQ process). Do not run old
   and new workers simultaneously: old code does not participate in the lock.
2. Apply `alembic upgrade head` (revision `20261028_0089`). The check-constraint
   replacement uses a five-second lock timeout and avoids a full-table scan.
3. Start the updated services. No new Python libraries are needed.
4. Check effective environment overrides: defaults are `BROADCAST_BATCH_SIZE=100`,
   `BROADCAST_CONCURRENCY=12`, `BROADCAST_MESSAGES_PER_SECOND=20`. The old
   `BROADCAST_SEND_INTERVAL_MS` no longer controls the worker. Concurrency is capped
   at 16 and pacing at 25 requests/second. Each active run needs a lock connection,
   coordinator connection and up to concurrency delivery connections; account for
   all worker processes when setting PostgreSQL connection limits.
5. Measure a normal campaign against reachable recipients using batch timing,
   Telegram 429/403 counts and final successful messages divided by elapsed time.
   Reduce concurrency/rate if DB latency or Telegram rate limits rise.

Rollback: stop consumers first, downgrade the migration, then start old code.
Downgrade converts any in-flight recipients to failed, not pending.

## Verification

`tests/test_broadcast_delivery.py` exercises the full worker and message persistence
against disposable PostgreSQL, with simulated Telegram HTTP latency. It verifies
single ownership across runs/campaigns, pause/resume without duplicate requests,
403 diagnostics, interrupted delivery, migration upgrade/downgrade, media reuse,
429 pacing and no automatic retry of read timeouts.

The first local run delivered 300 messages with 300 ms simulated Telegram latency
in 16.61 seconds (1084/minute). This is a controlled application benchmark, not a
measurement of the production server or Telegram. Blocked/deactivated recipients,
media uploads, intentional delays, other bot traffic and Telegram restrictions
reduce successful throughput.
