# Counter hotfix failure: production follow-up

The subsequent implementation and MAIN deployment requirements are in
`docs/chat-counter-fix-20261109.md`. This document preserves the failed-rollout
analysis; it is not the current rollout guide.

## Status and Evidence

`549d04e` passed local regression but failed the approved production rollout.
MAIN API/assets were rolled back to `b7a32b6`. No migration, data rewrite, queue
replay, worker restart, secret or assistant change was performed. Do not promote
`549d04e` unchanged, including as an incidental part of a later assistant release.

Private local evidence, not repository artifacts:
`/Users/art/.codex/backups/crm-mvp/20261108-hotfix/DEPLOY_REPORT.md`,
`readonly-supplement.json`, `candidate-verbose-plans.json` and `observation.jsonl`.
Full warning window: 08 November 2026 15:52:28-16:09:08 UTC. These are post-patch
observations, not the earlier two-hour incident report.

## Confirmed Failure Modes

HTTP counters: 191 successes, 88 failures / 279 responses. There are 69 detailed
counter failure warnings; do not sum these with HTTP failures. Cache cooldown and
same-key follower failure paths need not produce a new aggregate warning.

| Phase | Warnings | Project breakdown | Meaning |
| --- | ---: | --- | --- |
| counter_pool | 52 | Vacancies 22, Ru invest 16, Alinka 14 | One API-wide counter connection, pool wait ~0.5s |
| aggregate | 14 | Vacancies 12, Ru invest 2 | SQLSTATE 57014, ~3s statement deadline |
| lease_cleanup | 3 | Ru invest 2, Vacancies 1 | Cleanup phase exceeded its separate deadline |

The last group does not identify a specific SQL lock: the phase includes obtaining
a general connection, loading project settings, selecting/updating expired leases,
writing audit rows and commit/cancellation. No exact blocking query was captured.

For successful scans that emitted slow warnings (NOT all successes): aggregate
median Vacancies 2176ms (42 samples), Ru invest 1484ms (33 samples). Thus even
successful queries commonly hold the single counter connection longer than the
0.5s allowance of another scope. Request coalescing is per project/bot key; the
connection pool is shared across all keys. This isolates intake from counts but
does NOT isolate one project's counters from another project's counters.

The 3s error marker also covers pool wait failures. A failed attempt to acquire a
connection therefore temporarily suppresses a new attempt for that scope, even
though its SQL was never executed. Increasing SQL deadlines alone would keep the
single slot occupied longer and would not fix this contention.

The counter GET also depends on writable lease cleanup. Cleanup failure currently
fails the counter response without attempting its read-only aggregate. Removing
that dependency requires preserving timed release/audit and assignment semantics,
not simply deleting cleanup or ignoring its errors.

## What the SQL Plans Actually Prove

After rollback, bounded READ ONLY EXPLAIN VERBOSE without ANALYZE was collected for
the literal candidate and UUID-parameterized custom/generic variants. JIT and
parallel gather were disabled only within the diagnostic transactions.

- Tag membership and both submission checks are `hashed SubPlan` in these plans.
  They must NOT be described as a sequential table scan for each chat.
- UUID-parameterized generic and custom plans differ, but this is not the exact
  asyncpg plan: threshold/status parameters remain literals. It neither proves
  nor excludes a production prepared-plan problem. Do not force custom plans
  globally based on this limited comparison.
- JIT off / parallel 0 were verified in the hotfix counter connections, and SQL
  timeouts remained. JIT was not a sufficient explanation or fix.
- Plans still join broad lead/completion sets. Runtime node timings, buffer reads,
  spill batches and actual row counts were not measured. Cost units do not reveal
  where execution spent its three seconds.

Table layout differs substantially from the local empty-payload benchmark:
about 204k chats, 205k leads, 203k funnel states; heap sizes ~55MB / 361MB / 202MB.
Leads contain confidence metadata/reasons; states contain runtime JSON. Chat
indexes are ~984MB versus ~55MB heap. Dead tuples are present. These facts justify
matching the workload and examining index health, NOT unapproved REINDEX/VACUUM
FULL or attributing current counter errors to a particular bloated index.

## Other Production Observations / Limits

- Chat list accesses captured during rollout were 228 HTTP 200; this does not
  establish their latency or prove all dialog operations were healthy.
- No real `/tracking/link-options` traffic was observed. Browser refresh uptake
  and the frontend performance benefit were therefore not verified on production.
- Connections 39, intake backlog 0, dispatch/scheduled overdue >30s both 0; review
  stayed 77. No evidence of new delivery regression or lost data in this window.
- 81.3% failures before versus 31.5% during rollout came from different traffic and
  windows. Do not call that a controlled benchmark or infer a regression from it.

## Required Next Implementation / Acceptance

1. Reproduce the failure locally with the REAL one-connection counter pool and
   real Redis: a slow large scope, two smaller projects and distinct bot scopes,
   arriving together. Existing follower QA monkeypatches the session factory;
   the 100k workload runs one aggregate at a time. They missed this failure mode.
2. Redesign admission/refresh rather than adding DB connections blindly. Coalesce
   each scope and coordinate the shared execution budget across scopes. Cache an
   explicitly timestamped last-good snapshot; only serve it with freshness state
   and a bounded age, never fabricated zeroes or another project's snapshot.
   A first load without a snapshot must have a bounded, observable pending path.
   Preserve immediate/manual refresh semantics explicitly and test them.
3. Decouple lease maintenance from counter availability without changing who owns
   a chat or losing lease-expiry audit. Check existing periodic cleanup coverage,
   use a bounded worker/batch if needed, and test expiry/read-after-release races.
4. Profile the remaining aggregate on an isolated restored/synthetic copy with
   production-scale payload widths, distributions, 4MB work_mem, CPU limits and
   simultaneous scopes. Compare exact metrics against the reference. Optimize
   only nodes demonstrated slow, including small-project scans across broad sets.
   No live EXPLAIN ANALYZE or production load test without separate approval.
5. Add a counter-specific gate: concurrent real-pool requests, cold/warm cache,
   Redis outage, slow/error leader, cross-project fairness, bot/project revision,
   cancelled clients, deleted/reset leads, expiry and viewer permissions. Assert
   both correctness and bounded SQL concurrency/latency, not only a test count.
6. Another rollout requires approval, matching API/assets and refreshed browsers.
   Observe actual counter statuses/phase timings and delivery health on comparable
   traffic; revert on the agreed gate. No schema downgrade, queue replay or global
   timeout/pool changes as a substitute for resolving these failure modes.

This document records analysis, not a newly implemented runtime fix. Source changes
must be tested against the above reproduction before the next deployment claim.
