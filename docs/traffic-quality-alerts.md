# Traffic quality alerts

## Rollout and compatibility

Apply Alembic revision `20261002_0079`, deploy the API, alert worker, buyer bot
and frontend together. The new tables are additive; downgrade removes only
quality settings, state, acknowledgements and delivery history. Export those
tables before a downgrade if their configuration must be retained.

New monitoring is disabled by default. Existing funnel execution, attribution,
channel approval and start policies are unchanged. Legacy buyer alerts remain
active until the project enables the new quality monitor. Enabling it replaces
legacy quality alerts for that project, including when no rules are enabled.

Administrators configure Settings / Quality of traffic. A tracking link's edit
dialog contains its overrides. Only changed fields override the project rule;
other fields inherit later project changes. Concurrent saves use revision
checks. A referenced tag cannot be deleted until removed from the rules.

## Calculation

Quality rules evaluate acquisition cohorts, not calendar activity totals.
The selected period ends before the configured maturation delay. Conversions
are observed until the evaluation time. People with the same confirmed Telegram
identity and link count once. Tags and statuses reflect their current state.
Reg/FD are person milestones; RD counts events, with a separate redepositor
metric. Intersection metrics distinguish registered depositors and request
subscribers from unrelated direct joins.

Buyer statistics use the same activity metrics service as the CRM. Their UTC
calendar dates are intentionally different from quality cohort windows.
Gambling summaries display registration, FD and RD rather than submissions.

Insufficient sample, coverage, absent metrics or division by zero produces
"insufficient data", never an invented zero or recovery. Spend uses entered
daily expenses, one currency, whole days in the configured project timezone;
it does not estimate missing expenses from CPM. Missing click observations
are not replaced with bot starts.

Expressions support numeric metrics, arithmetic, comparisons, `and`/`or`,
`percent(a,b)`, `min(a,b)` and `max(a,b)`. They are parsed with an allowlisted
AST interpreter, not Python eval. Comparisons return 1 or 0; a boolean rule
can use threshold 0.5 with operator greater-than and recovery 0.

## Delivery

Checks require confirmations at least ten minutes apart. Recovery has its own
threshold; repeats have a configurable interval. Messages group up to three
rules per link. A database outbox survives restarts. Before sending, the worker
rechecks project enablement, rule version, link ownership, user access and
incident generation. Telegram requests run outside database transactions.

Buyer acknowledgement/snooze applies only to that recipient and incident
generation. It does not silence administrators or a later incident. Delivery
errors and attempts are visible in the settings journal. Buyer destinations
use buyer_telegram_id; admin destinations use telegram_id and the admin bot.
Users must have started the corresponding bot and have access to the project.

Telegram sendMessage has no idempotency key: a connection loss after Telegram
accepts a message can result in a repeated notification on retry. The database
prevents duplicate scheduling but cannot guarantee exactly-once network delivery.

## Buyer bot

The menu offers paginated/searchable owned links, activity statistics, tag
charts and quality alerts. Creation supports direct bot/channel links and
Facebook campaigns with available domains and landing templates. Existing
project permissions and channel policies still apply. Custom landing assets
are copied into independent storage, not shared with the source campaign.

## Production acceptance

1. With monitoring disabled, verify an existing funnel/link and legacy alert.
2. Configure one rule; preview real data without sending, including an empty
   sample and zero denominator. Check the shown acquisition dates.
3. Enable monitoring on a test project and verify buyer and admin delivery,
   confirmation delay, cooldown, recovery and personal acknowledgement.
4. Change link ownership or remove access before delivery; confirm stale
   recipients are excluded. Disable monitoring and verify queued alerts cancel.
5. Compare buyer 7-day statistics with the same CRM link and UTC period.
6. Create bot, request-to-join channel and Facebook links; verify their public
   destination, attribution and unchanged approval/start settings.

Automated tests exercise formulas, real PostgreSQL cohorts, permissions,
revision conflicts, notification scheduling and migration upgrade/downgrade.
Live Telegram delivery and the full browser workflow require acceptance in
an authorized test project; successful unit tests are not a substitute.
