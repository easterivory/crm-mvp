# Tracking: funnel journey

Open Tracking, select project/bot/buyer and acquisition dates, then choose
`Прохождение воронки`. The same tab is available inside a link's details,
where its link filter remains applied.

Select a published funnel and an unanswered threshold (default 24 hours).
Each count opens a paginated lead list with attribution, current status and
tags. Dialogs open in a new tab, leaving report filters and position intact.

## Definitions

- Dates select the existing tracking acquisition cohort: the lead's current
  cycle start, falling back to creation time, in UTC. Results are its progress
  up to now, not the number of step events occurring during those dates.
- Reached: distinct leads with an `entered` event in this cycle. Repeated
  visits and published versions of the same funnel/key do not add duplicates.
- Continued: another step entered later, or a runtime snapshot confirming
  departure/completion. This is departure from the step, not necessarily the
  visually adjacent step: branches and backward transitions also count.
- Current: the active runtime is on this step and not completed.
- Waiting: current, waiting for an answer, not paused, no delivery/transition job.
  Input retry/no-reply timers do not hide a chat awaiting an answer.
- Delayed: current, not paused, with a pending/running scheduled job.
- Manual: current paused runtime, including manual review/manager takeover.
- Stalled: waiting with neither step entry nor a client message within the
  chosen threshold. This is not proof of permanent abandonment.
- Current state columns are independent of historical continued counts.
  Stalled is a subset of waiting; do not sum the columns as distinct leads.

No historical events are fabricated. PostgreSQL timestamps can be equal for
multiple entries inside one transaction; the runtime snapshot provides an
additional departure signal. If that snapshot was deleted and only equal-time
historical events remain, their order cannot be reliably reconstructed.

## Step identities

Labels include funnel, published version, `#N`, and title. Numbers follow the
builder's ordering: Y, X, then UUID. Trigger/finish steps remain in numbering,
even when a selector excludes them. Numbers describe the chosen version's
layout, not execution order. Stable keys merge history across versions;
the latest published/archived occurrence of each key supplies its label.
Old keys removed from the latest version retain their historical version label.

The old current-distribution API remains unchanged for compatibility. Its
UI no longer calls adjacent snapshot differences "Dropoff".

## Compatibility and checks

This is read-only reporting; no migration, worker or funnel configuration
change is required. Buyer filters and project access use existing tracking
authorization. Reset/deleted chats and pre-cycle events are excluded.

Production smoke checks:
1. Compare numbered steps with the same version in the builder.
2. Compare one link and one buyer with the existing tracking totals.
3. Open reached/waiting/manual/delayed counts and verify several actual dialogs.
4. Verify looping leads count once, and old-cycle events do not count after reset.
5. Verify another project's report/link cannot be requested and buyers cannot
   inspect another buyer's leads.
