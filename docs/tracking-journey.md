# Tracking: configurable stage journey

Open Tracking, select project/bot/buyer and acquisition dates, then choose
`Движение по этапам`. This replaces the old technical-step table, not a
separate vacancies report. The same tab is available inside a link's details,
where its link filter remains applied.

Without a saved configuration, the tab opens an automatic `Все шаги` overview
of the selected funnel's published/archived stable steps (up to 399). It needs
no tag or VIP configuration and never treats the last technical step as VIP.
Automatic mode resolves steps again after publication; saved custom stages are
not replaced. `Вид` switches between this overview and custom stages.
The vacancies preset selects existing exact-name tags, including `Шаг 1` through
`Шаг 4`, HOT, HOT HOT and VIP. Missing matches remain unselected rather than
being guessed from generic message/question titles. Selecting tags or steps
fills the stage name; manually edited names stay unchanged. The name-reset
button restores the name from the selected sources.

An administrator selects `Настроить этапы`, optionally chooses the vacancies
preset, and binds its stages to stable step keys or tag IDs. Entry and accepted
answer are distinct conditions. The last stage is a tag-based outcome (e.g. VIP),
never inferred from partner submission/status. An optional offer stage defines
the offer-to-outcome conversion. Multiple conditions within a stage use OR.
The first stage is fixed to acquisition; intermediate names/order are editable.
Scope can be the whole bot or one funnel. For whole-bot analysis, bind step
references explicitly across its published funnels/copies; identical names,
numbers or keys in different funnels are not automatically merged. Funnel-only
scope includes first acquisitions whose first known funnel is the selected one,
plus start-only people with no retained funnel-entry evidence yet. Later resets
into another funnel do not count as a new acquisition. Tag-based outcomes still
follow the confirmed Telegram identity through account handoffs.
Each count opens a paginated person list with attribution and current tags.
Dialogs open in a new tab, leaving report filters and position intact.

## Definitions

- Acquisition is the earliest retained user /start or funnel-entry evidence,
  across all bots in the project. Channel auto-start does not require /start.
  A Telegram ID identifies a person; absent IDs fall back to chat identity,
  never a guessed match by name/username. Deleted/reset origins participate in
  deduplication, so later duplicates cannot become new arrivals.
- Bot/link/buyer/date filters apply AFTER selecting the first origin. The
  configured funnel belongs to that origin bot. Membership in related bot/account
  chats preserves person identity and allows tag-based handoff outcomes.
  Start attribution uses the original message's link snapshot (including no
  link), channel auto-start uses its successful subscription event snapshot.
  Legacy entries without these snapshots fall back to the retained chat link.
- Dates use Moscow timezone, inclusive dates / exclusive next-day boundary.
  Progress is measured up to the report time for people acquired in the range;
  it is not an activity-date report. Other tracking APIs keep their semantics.
- Reached: the first retained event matching a configured stage. Loops, resets
  and repeated tag assignments do not increase unique person counts.
- Remaining: highest configured reached stage, provided outcome is not reached.
  This is not a claim that everyone permanently abandoned the funnel.
- Stalled: remaining and an active unpaused runtime awaiting an answer beyond
  the configured idle threshold (default 24 hours), without pending delivery.
  Manual pauses, completed runtimes and scheduled delivery are not stalled.
- Adjacent conversion requires the same person and next-stage timestamp >=
  previous-stage timestamp. Skipping a configured stage does not invent it.
  Overall outcome conversion uses all acquisitions; offer conversion uses only
  people who reached the offer before the outcome. Zero denominator is null.
- Daily/weekly/monthly charts group by acquisition date, not event date.
  Empty periods are explicit zeros; weeks start on Monday in Moscow.
- Related physical chats are separate from the unique-person denominator.

No historical events are fabricated. Migration 0084 seeds currently assigned
tags using their existing assignment timestamps (`legacy_snapshot`). Previously
removed tags cannot be reconstructed from current membership. A database AFTER
INSERT trigger records all future assignments, including raw import inserts,
funnel actions and manual changes. ON CONFLICT replays produce no new fact;
tag removal/rename/deletion does not erase retained assignment history. Real
database facts and tag assignment changes share a transaction. Equal timestamps
may indicate automatic transitions in a single transaction, not strict ordering.

## Step identities

Step selectors include funnel, published version, `#N`, and title. Numbers follow the
builder's ordering: Y, X, then UUID. Trigger/finish steps remain in numbering,
even when a selector excludes them. Numbers describe the chosen version's
layout, not execution order. Business-stage numbers reflect the configured
analytical order. Explicit (funnel ID, stable key) references merge versions;
the latest published/archived occurrence of each key supplies its label.
Old keys removed from the latest version retain their historical version label.

The old current-distribution API remains unchanged for compatibility. Its
UI no longer calls adjacent snapshot differences "Dropoff".

## Compatibility and checks

Apply migration `20261012_0084` before deploying the API/frontend; downgrade
drops only the new configuration/history tables and trigger, not lead tags.
No funnel execution, worker, advertising events, lead statuses or VIP submission
rules change. Analytical stages are opt-in, scoped by project/funnel; only
admins/superadmins can edit. Buyers keep existing ownership filters. Old
`/metrics/journey`, `/metrics/journey/chats` and step APIs remain unchanged.
The legacy technical journey remains current-cycle/UTC reporting for API users.

Production smoke checks:
1. Compare numbered steps with the same version in the builder.
2. Configure stage conditions and verify one link/buyer using real source dialogs.
3. Open reached/remaining/stalled counts and verify several actual dialogs.
4. Verify looping/restarted leads count once, and removed VIP retains conversion.
5. Verify another project's report/link cannot be requested and buyers cannot
   inspect another buyer's leads.
