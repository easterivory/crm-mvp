# MAIN Counter Recovery: 09 November 2026

## Status

This is a new implementation after the failed `549d04e` rollout, not a request to
redeploy that release unchanged. Historical evidence is in
`docs/chat-latency-followup-20261108.md`. No production deployment is authorized
by this document. MAIN was last reported rolled back to `b7a32b6`.

No new dependency, migration, index build, data backfill, secret or project setting.
Counters remain read-only. The existing one-connection/no-overflow counter pool,
3s SQL deadline, JIT off and parallel gather off are retained. No global DB/pool
setting is raised. No conversion, delivery replay or customer message is sent.

## Changes

### Refresh Admission and Snapshots

- One active refresh per API process. A FIFO application gate is BEFORE acquiring
  the reserved connection, so another scope does not fail its 0.5s pool checkout.
  Maximum 16 active/queued distinct scopes; callers for the same scope share a task.
- Cache key includes project, bot scope, project revision and counter rules, not
  the requesting manager. Personal counts are derived only after authorization;
  raw manager maps never leave the service. Equivalent single-bot encodings share
  a key, while contradictory bot filters retain their original AND semantics.
- New Redis namespace `crm:chat-counts:v2:` stores counts plus an `as_of` timestamp.
  No existing Redis key/queue is deleted. Fresh window 15s, maximum snapshot age
  60s; expired, malformed or future-dated snapshots are not served by the API.
- A valid older snapshot returns immediately with `counts_stale=true` and
  `counts_refreshing=true` while a deduplicated refresh runs. A failed refresh
  retains last-good values within the age bound, explicitly marked stale.
- A cold request waits at most 6s. Without a valid result it returns HTTP 503 and
  Retry-After 2, never fabricated zeroes. Queue pressure does not discard a valid
  known snapshot. Failures have a bounded 3s cooldown rather than hot retry loops.
- Local fallback: at most 128 scoped snapshots and 128 failure entries. Redis
  outages retain local admission/cache limits. Across API processes, a short
  token-owned Redis lease prevents duplicate same-scope SQL. Waiting for a peer
  releases local admission so it cannot block unrelated scopes; do not infer one
  global SQL slot across multiple API processes or expand their count blindly.
- Refresh jobs capture plain arguments, not a request DB session or ORM objects.
  Client cancellation does not kill a shared read. API shutdown cancels/drains
  jobs before closing Redis/reserved pools. Pending jobs are disposable reads,
  never a business-delivery queue.
- Phase diagnostics distinguish admission, checkout and aggregate; scope hash
  suffix/project ID are logged without SQL parameters, text or raw provider data.

### Aggregate

The query no longer joins all completed funnel states. Unassigned leads already
qualify for the unread workspace; completion is looked up only inside CASE for
assigned, unread, low-score leads without an active submission. A unique-chat
scalar lookup uses the existing state/chat index. Tag/submission membership remains
hashed; business predicates, soft deletes, resets, confidence mode and bot scopes
are unchanged. No speculative cleanup/reindex of production tables.

### Lease Expiry

Counter GET no longer performs writable lease cleanup. Existing list/detail/action
paths retain their immediate expiry handling. API lifespan starts a background
maintenance loop without delaying readiness, with 30s between bounded passes and
a 20s pass cap. A token-owned Redis lease (25s) prevents overlapping API processes;
Redis failure skips a pass, not API reads. It pages at most 8 active lease-enabled projects and 100 expiries/project;
2s phase budgets, transaction-local SQL 1.5s / lock 300ms. One project failure does
not stop others, and incomplete writes/audit roll back. Existing SKIP LOCKED and
audit logic prevent double release. With more than 8 projects, pages rotate.

Shutdown cancels and drains the loop, rolling back unfinished writes before
closing clients. This is API maintenance, not an ARQ delivery job. Jobs code and
cron registration are unchanged. Expiry is still enforced on chat/list access.
The existing jobs process cannot safely drain on SIGTERM: installed ARQ defaults
to cancelling active tasks. Therefore this release MUST NOT restart jobs.

### Browser / HTTP

`counts_as_of`, `counts_stale`, `counts_refreshing` are additive response fields.
The UI labels older data and its calculation time. A background refresh gets up
to three cheap follow-up reads at 2s intervals, only in the visible current scope;
normal polling stays 15s. Manual refresh sends `refresh=true`, recomputes even a
fresh cache entry, and is not lost behind an in-flight ordinary poll. Repeated
clicks coalesce. Missing initial values show `...`; no notification storm.

Counter responses, including handled errors, are private/no-store and vary by Authorization.
This header is limited to the counter endpoint; advertising URLs/CDN/DNS are not
changed. Older browser tabs need a page reload for the UI changes. Older clients
can ignore the additive metadata, but do not display its freshness indication.

## Verification

- `tests/test_chat_counts_coordination.py`: actual PostgreSQL pool size 1, no
  overflow, 0.5s checkout and Redis. The original implementation failed the
  three-project test with pool timeouts. The new path passes FIFO/isolation,
  stale-while-refresh, real SQL timeout, cooldown, expired snapshot rejection,
  Redis outage/local fallback, cancel/shutdown, manual refresh, project revision,
  equivalent/distinct bot scopes, queue cap, remote-owner lock and HTTP auth/privacy.
- `tests/test_chat_lease_maintenance.py`: API lifecycle start/drain, Redis mutual
  exclusion and token-owned unlock, timeout/cancellation rollback, loop recovery,
  no ARQ registration, expiry versus
  current assignments, concurrent cleanup with one audit, failure-after-write
  rollback, another project's progress, project pagination and disabled projects.
- `tests/test_chat_counts_large_payloads.py`, explicit `CRM_LARGE_QA=1`: 200k
  synthetic chats, wide confidence/runtime JSON, 90/10 project distribution,
  sparse assignments, overlapping tags and 4MB work_mem. Legacy join and new
  query agree exactly. Initial local run 489.5ms / 237.4ms, 80 indexed state
  probes; simultaneous three-project reads also complete. Local EXPLAIN ANALYZE
  is confined to this disposable fixture, never production.
- Existing 100k denser-assignment profile also passes: reference 410.1ms / new
  168.6ms in one local run, matching metrics. These are not production guarantees
  or a claim to emulate the production CPU limits/cache/LLVM environment exactly.
- MAIN planning-only check: `/Users/art/.codex/backups/crm-mvp/20261109-counter-plan.json`
  confirms no broad state join and an indexed SubPlan inside CASE, with hashed
  tag/submission SubPlans. Planner cost is not runtime; no live ANALYZE was run.
- Playwright at 390/1440: pending/stale time, follow-up recovery, forced refresh
  behind normal polling, one-flight requests, old-scope abort, initial 503,
  preserved values, no toast spam, metadata isolation and hidden-tab pauses.
  Screenshots: local `tmp/chat-counts-qa/`. TypeScript/Vite production build passes.

Prior regression before the API lifecycle change: 1229 passed. After that change,
the complete PostgreSQL/Redis run with `CRM_LARGE_QA=1` produced **1234 passed,
5 skipped, 7 subtests passed** and one test-fixture failure: a mocked maintenance
result omitted `projects`, unlike the real function. Only that mock was corrected;
production code was unchanged. The complete coordination/maintenance set is then
rerun under the installed uvloop policy: **22 passed** in 28.89s.
Existing dependency/FK-cycle and JS bundle warnings remain. This is local
acceptance, not a production-success claim.

## Rollout / Rollback

1. Obtain explicit rollout approval. Do not ship unrelated dirty native OAuth
   changes, enable assistant flags, modify Bunny/TLS or deploy postback_gateway.
2. Save rollback API image/assets. Record jobs image/container IDs without changing them.
   Build a clean release first.
   Starting from deployed `b7a32b6`, include the earlier seven runtime files of
   `549d04e` (including `app/core/telegram_intake.py` and light tracking options),
   plus the current `app/main.py`, `app/api/v1/routers/chats.py`, `app/schemas/chat.py`,
   `app/services/chat_service.py` and new
   `app/services/chat_lease_maintenance_service.py`. Use the CURRENT versions of all files.
   Prefer a clean complete release image; a diff only against local `549d04e`
   omits required files when overlaying a `b7a32b6` image. Exclude live .env/data.
3. Update ONLY API + matching frontend assets, using a service-scoped command
   with `--no-deps`; do not use root deploy scripts or a general compose up.
   Keep the old jobs container/image/process untouched, including no signals.
   Changing future ARQ shutdown settings cannot make the current worker drain.
   Do not restart PostgreSQL/Redis or unrelated customer-delivery workers, migrate
   schema, flush cache/queues or replay review. Leave webhook/bot settings alone.
4. Reload browser tabs. With an authorized manager, check actual list/dialog,
   ownership, counter freshness/refresh and light link options. Verify API
   maintenance starts and has no errors, not merely that health returns 200. Existing read paths
   still enforce lease expiry; do not reset leases manually as a test.
   Check the counter endpoint's private/no-store response at the edge too; do not
   change global Bunny rules/advertising routing to solve a scoped cache problem.
5. Observe comparable normal multi-project traffic for 15-30 minutes: cold and
   warm counter HTTP status, as_of age/stale flags, pool/admission/SQL timings,
   CPU, actual DB connections, lease warnings/audit and intake/dispatch/scheduled
   queue age. A 200 carrying persistently old data is NOT a successful gate.
   Do not load-test production or create real conversions.
6. If the gate fails, roll back matching API + assets; jobs remains untouched. No schema downgrade,
   data rewrite, cache flush or business-queue deletion. Correct lease expiries
   are normal audited operations, not data to restore from a backup.

Residual risks: cold scopes still have a bounded unavailable path under sustained
SQL failure/queue pressure. Cross-process contention and a production payload/CPU
mix require the approved live gate; local test counts alone are not acceptance.
