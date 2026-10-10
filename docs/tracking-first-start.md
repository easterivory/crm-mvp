# First Telegram start in project statistics

The `starts` metric counts the earliest incoming `/start` for a Telegram user
within a project. Different bots or tracking links do not create additional
starts for that person in the same project. Different projects count separately.
`/start@bot` and start payloads retain their existing recognition rules.

The earliest start is selected over retained history before applying report
dates, bot, buyer or link filters. Its original message tracking link owns the
start; changing the chat's current attribution does not move it. An untracked
first start stays in the unattributed total even if a later start has a link.
Equal timestamps are resolved consistently by message UUID. Missing legacy
Telegram IDs deduplicate within their chat, not across unrelated chats.

Retained reset/soft-deleted chats participate in identifying the first start,
but remain excluded from displayed totals by the existing visibility filters.
Hiding an original chat never credits a later bot with a new first start.
Physically removed history cannot be reconstructed by this aggregation.

One shared SQL predicate is used in project/bot/link/unattributed totals,
daily charts, buyer-filtered rows, fixed-per-start modeled spend and the legacy
traffic endpoint. Historical reports recompute immediately; no migration or
data rewriting is required. Modeled per-start costs may decrease accordingly;
manual spend records and channel subscription costs are unchanged.

This does not merge chats/leads, change funnel execution, suppress Telegram
events or alter stored attribution. Lead, submission, registration and deposit
metrics retain their own existing counting rules; this update only deduplicates
`starts`, not every downstream metric.

Verification: run `tests/test_tracking_first_project_start.py` with
`CRM_TEST_POSTGRES_URL` pointing to an isolated PostgreSQL instance. The test
creates/drops its own schema and uses real repositories without mocks.
