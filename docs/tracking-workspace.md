# Tracking workspace

The refreshed tracking view changes presentation and adds read-only queries.
It does not change funnel execution, channel subscriptions, attribution, CAPI
or traffic-quality alert settings. No migration or dependency is required.

## Controls

- Buyer filter applies to project summary, daily values, tags, reached steps,
  cohort conversion and the link list. Buyer-role users remain restricted to
  their own links; an explicit foreign buyer filter returns 403.
- The link list loads all pages instead of silently stopping at 100 links.
- Metrics settings choose up to 20 standard metrics, tags or published funnel
  steps. Clicks are off by default. Chart checkboxes hide individual lines;
  removing a metric also removes its summary tile.
- The optional peak=100 scale compares relative dynamics without changing the
  underlying totals. Money otherwise uses a separate right axis.
- CSV exports selected raw daily values, not normalized chart values. Failed
  or pending custom queries disable export rather than exporting fake zeros.
- View preferences are local to this browser, user and project, not a global
  project policy. A link detail view uses the same configurable component.
- Channel link cards and details include the downstream bot funnel metrics;
  the initial destination does not hide registrations, deposits or submissions.

## Meaning of the counts

Existing activity metrics retain their existing definitions. Tags count current
tag membership for leads acquired during the chosen UTC date range.
Reached-step metrics also use acquisition dates, counting each lead once if an
`entered` event exists after the current lifecycle start. Re-entry is not a new
person. Published/archived versions of the same funnel and stable step key are
combined. Different funnels are not merged. Old funnels without step logs
cannot have their missing step history reconstructed by this update.

Two different calculations are intentionally named separately:

1. **Metric ratio:** any selected result total divided by the selected base
   total. Activity windows and cohort dates can differ. This is not claimed to
   be a person-level funnel conversion and may exceed 100%.
2. **Same-cohort conversion:** leads entering during the selected dates who
   satisfy the base condition; the numerator is the subset satisfying the
   result condition now. Supports all entering leads, successful submissions, registration, FD,
   people with RD, current tags and reached steps. Repeated lifecycle events
   do not duplicate a lead. It is intersection-based, not chronological:
   ordering of the two conditions is not enforced, especially for current
   tags whose application time is not stored here. Missing denominator is
   displayed as a dash, not 0%.

These are lead records scoped by the confirmed tracking link. This release
does not invent cross-account identity links or retroactively assign traffic.

## Acceptance

Run `tests/test_tracking_workspace.py` with `CRM_TEST_POSTGRES_URL` pointing
to a disposable PostgreSQL. It creates and removes a unique test schema.
It verifies buyer filtering, denied foreign access, repeated step events,
multiple versions, reset boundaries, tags and lifecycle intersections using
real SQL, not substituted service responses.

Before broad rollout verify a submission and gambling project, a channel link,
one buyer, a tag and a historical step. Compare base metrics with the previous
release for identical dates. Hide clicks, reload the view and confirm that the
preference persists. Check selected CSV columns and zero-denominator display.
