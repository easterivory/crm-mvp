# Chat latency / counters: 08 November 2026

## Production Gate Failed

Release `549d04e` was deployed with user approval, observed, then rolled back to
`b7a32b6`. It is NOT production-validated: 88/279 counter requests returned 503.
Do not redeploy the same patch unchanged or silently include it in an assistant
release. Read `docs/chat-latency-followup-20261108.md` before further work.
The replacement candidate is documented in `docs/chat-counter-fix-20261109.md`;
it requires API + matching assets only. Jobs must remain untouched because its
current ARQ process cannot safely drain on termination.

## Evidence

MAIN revision `b7a32b6`, schema `20261107_0098`. Read-only collection covers
16:08:13-18:08:13 MSK. Files are in the local incident archive; do not publish them.

- PostgreSQL: 980 statement timeouts of the shared workspace-count aggregate.
- API access log: 1656 counter responses with HTTP 503, 382 with HTTP 200.
- CPU was heavily occupied during the later resource snapshots. No restart, OOM,
  current blocking chain, Redis stall or global SQL connection exhaustion found.
- Original EXPLAIN has per-row tag/state checks, two parallel workers and 56 JIT
  functions with optimization/inlining. JIT overhead is a hypothesis, not a measured
  production duration. Parallel-worker termination follows query cancellation.
- Chat filter metadata used full `/tracking/links`, including per-link spend and
  step-title calculations. The page reloaded metadata when chat filters changed.

Slow-request logs omit fast successes. Their quantiles are NOT all-request p95.
Other Telegram network failures, historical review rows and backup-size errors
are separate issues; this patch does not replay or resolve historical deliveries.

## Narrow Patch

1. Counter-only DB connections disable JIT and parallel gather. Keep the existing
   one-connection/no-overflow pool, read-only mode, 3s SQL and 1s lock deadlines.
   No global PostgreSQL configuration, general pool or Telegram intake change.
2. Build selected-tag membership once within project scope; left-join the unique
   completed funnel state instead of probing it per row. Preserve unread, manager,
   priority, reset/deleted, submission and bot-scope semantics.
3. Share counters for 5s in Redis. Followers wait up to 6s without holding a general
   DB connection. A 3s error cooldown bounds repeated failed scans. Redis outages
   still fall back to the existing bounded counter pool. No fabricated zero data.
4. Log phase/timing and SQLSTATE (lease cleanup / counter pool / aggregate), without
   SQL parameters, message text or raw provider errors.
5. Browser counts: one in-flight request per project/bot scope, 15s visible-tab
   polling, abort/discard old scopes, manual refresh. Last valid values remain with
   an inline warning; initial unavailable values are `...`, not zero. List polling
   remains 5s; background list/dialog polling pauses while the tab is hidden.
6. Separate filter/project metadata loading from list/filter polling.
   `/api/v1/tracking/link-options` returns only ID/title/code with the existing
   project/buyer/bot permissions and pagination, without report computation.
   Full tracking API and reports remain unchanged.

## Verification

- `tests/test_chat_counts_performance.py`: old/reference versus new counters across
  manager, project format, confidence, bot, deleted/reset, completion, submissions,
  foreign and overlapping tags. Slow single-flight followers, error cooldown and
  safe logs; actual counter-connection GUC isolation.
- Explicit `CRM_LARGE_QA=1`: 100,000 chats with populated funnel states and three
  overlapping tags. Same metrics; local initial run 406ms reference / 141ms new.
  Homebrew PostgreSQL has no usable LLVM JIT; this is NOT a production speed claim.
- Initial production candidate EXPLAIN ONLY: cost ~1.65m versus ~5.08m, no
  JIT/gather. Later VERBOSE EXPLAIN shows hashed submission membership SubPlans;
  describing the remaining checks as per-row correlated scans was incorrect.
  No diagnostic EXPLAIN ANALYZE was run; the later approved rollout did execute
  the actual endpoint on ordinary traffic and failed its acceptance gate.
- `tests/test_chat_link_options.py`: 100 links; constant query count, no full report
  serialization, manager/buyer visibility, inactive/legacy fallback, bot/project
  rejection, pagination, limit and output privacy.
- `frontend/tests/run-chat-counts.mjs`: Playwright at 390/1440px; failure/last values,
  no notification spam, overlapping refresh coalescing, project/bot cancellation,
  filter/metadata isolation, no full tracking API, hidden-tab polling, screenshots.
- Run full pytest with disposable PostgreSQL/Redis and `frontend/npm run build`.
  Screenshots are local `tmp/chat-counts-qa/`; fixtures never call a real server.

Final local run: **1210 passed, 7 skipped, 7 subtests passed**; the explicit 100k
profile also passed (five tests including the large case). Production frontend
build passed. Existing dependency/FK-cycle and bundle-size warnings remain; they
are not a claim of failure-free production operation.

## MAIN Rollout Boundary

No new migration, dependency, data repair, secret, queue or project setting change.
Do not deploy the separate postback gateway. Do not mix the unrelated, uncommitted
native assistant OAuth changes into this incident release.

Incident runtime files: `app/core/telegram_intake.py`,
`app/repositories/chat_repository.py`, `app/services/chat_workspace_counts_service.py`,
`app/repositories/tracking_repository.py`, `app/services/tracking_service.py`,
`app/schemas/tracking.py`, `app/api/v1/routers/tracking.py`; three changed chat UI
source files and the rebuilt `frontend/dist` (including its new hashed JS file).

After explicit rollout approval: retain rollback image/assets, build before the
maintenance window, update API and matching assets together, without DB/Redis/
worker restarts or migrations. Verify existing schema first. Do not run a blanket
deploy script without checking whether it recreates unrelated services.

After release: verify image revision, API health, a normal chat page/list/dialog,
counts and link options under an authorized account, manager visibility and live
incoming-message processing. Observe SQLSTATE 57014 / counter 503 and phase timings,
CPU, actual connection count and intake/scheduled queue age for 15-30 minutes.
Do not load-test production or replay review jobs. Roll back the API image and its
matching assets if failures persist; no schema downgrade or data rewrite needed.
Old browser tabs keep their old polling code until reload; ask managers to reload.

The code is locally verified, not a guarantee that all chat latency disappears:
tracking report latency and unrelated delivery failures require separate evidence.
