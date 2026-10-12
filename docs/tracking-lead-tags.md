# Tracking lead qualification

Project settings > Lead in tracking now selects one of two mutually exclusive
modes: statuses (the existing default) or tags. Tag mode matches any selected
project tag, regardless of lead status. A lead carrying several qualifying tags
is counted once. Switching modes preserves the other mode's saved selection.

The shared criterion is used by tracking totals/daily breakdowns, buyer analytics,
project header metrics, info-bot reports and qualified-lead traffic quality rules.
It does not change start deduplication, submission success metrics, attribution,
registration/deposit events or funnel execution. Date windows retain their
existing lifecycle/cohort semantics; this is not a count of tag assignments
within the period. Removing all matching tags removes qualification from the
current-status-based reports, just as changing a qualifying status did before.

Tags must belong to the selected project. Tag mode cannot be enabled with an
empty list. Create the project and tags first, then configure the mode. Existing
projects keep their status selections and require no configuration changes.

Rollout: back up, apply Alembic revision 20261012_0083, then deploy/restart API
and workers and update frontend. The migration adds safe defaults and has a
downgrade. The new code requires the migration before serving requests.

Local verification uses real PostgreSQL: legacy status counts, tag-only counts,
multiple tags, tag removal, foreign-project validation and switching back.
Upgrade/downgrade of 0083 is checked against a schema built from the preceding
model layout. Bootstrapping the entire historical migration chain from an empty
database currently hits an unrelated duplicate waiting_for_answer column in
revision 0012; this patch does not rewrite historical migrations.
