# AI runtime safety

## Deployment

1. Back up the database and apply `alembic upgrade head` (revision `20261008_0080`).
2. Deploy API, delayed workers and the frontend together. Drain running AI jobs
   before restarting workers. Old queued AI delivery jobs remain supported.
3. Preserve `AI_CREDENTIAL_ENCRYPTION_KEY` (or the existing `SECRET_KEY` fallback).
   Changing that key without re-encryption makes existing credentials unreadable.
4. Public provider endpoints require HTTPS. Private/self-hosted endpoints require
   `AI_TRUSTED_PROVIDER_ORIGINS`, for example `http://ollama:11434`. Entries are
   exact scheme/host/port origins, not wildcards. Configure API and worker equally.
   Previously configured private or HTTP endpoints must be explicitly allowlisted.

No new dependencies. Ordinary non-AI steps and disabled-AI projects retain their
existing execution path. New connection capability settings default to an empty
object; the adapter keeps the legacy protocol for unrecognised models. Known
OpenAI reasoning families use `max_completion_tokens` without temperature.
Explicit per-model overrides in AI settings take precedence, including JSON mode.

## Delivery and recovery

An AI step stores an execution/visit token, generated outcome and message progress
in `chat_funnel_states.runtime_json.ai_execution`. The outcome and extracted lead
fields commit together before delivery. State is rechecked after generation,
before each message and before transition. Pause, reset, version change or a new
visit invalidates the old execution. Generation does not hold a DB transaction
open during the provider call; delivery does not hold one during Telegram I/O or
typing delays in the scheduled worker.

After an explicit Telegram rejection (e.g. rate limit), the existing retry pipeline
resumes from the unsent message without another LLM request. If a worker dies with
a message marked in-flight, or Telegram returns a network timeout/5xx, acceptance
cannot be determined: the AI step pauses and emits an operational alert. The
system does not pretend Bot API has exactly-once delivery. Check the Telegram/CRM
history and use the existing manager resume/return-to-step controls. Returning to
the AI step explicitly creates a new generation and can incur a new charge.

An interrupted generation with unknown response also pauses instead of silently
repeating a potentially billable request. Operational alerts use the existing
backup/alert destination and must be configured to reach the team.

## Budget accounting

Configured project budgets reserve funds under a project-settings row lock before
each primary/fallback request. Reservations use configured model prices, an
intentionally conservative UTF-8 byte allowance for input plus protocol overhead,
and the maximum output-token limit. This can reject a request even when its actual
tokenised cost would fit. It is an application spending guard, not a provider-side
billing guarantee: prices and exotic model tokenisation must be checked against
the provider; provider account spending limits remain recommended.

Confirmed provider usage replaces the reservation atomically, including failed
structured-output/field validation and reasoning-token usage. Missing usage,
uncertain network outcomes and worker crashes keep the reservation allocated for
the applicable UTC day/month. They never automatically free possibly spent money.
The usage screen shows both confirmed cost and unsettled reservations separately.
Unsettled reservations are not extra confirmed charges and may represent either
an in-flight request or an interrupted/unknown one. Connection-test calls remain
superadmin-only and outside project budget accounting; they are billable tests.

## Checks

`tests/test_ai_runtime_safety.py` has pure validation tests and real PostgreSQL
concurrency, execution-recovery and migration roundtrip checks. PostgreSQL tests
require `AI_SAFETY_TEST_DATABASE_URL`; each run creates/drops a unique schema.
Optional real DNS verification uses `AI_SAFETY_TEST_NETWORK=1`. No mocks or paid
model calls are used by these new tests.

Manual production smoke check:

- Existing ordinary funnel follows its previous routes.
- AI primary and fallback each deliver once and record usage.
- Pause or move the chat while a model is answering: no stale lead-data update,
  subsequent AI messages or transition from the old visit.
- Simulate worker restart between delivered messages: confirmed progress resumes;
  uncertain in-flight delivery pauses and alerts.
- Concurrent requests cannot allocate beyond the configured budget, including
  fallback requests; the usage screen distinguishes reserves from confirmed cost.
- Check provider-specific model overrides and a real provider response with an
  approved key. Real paid-provider end-to-end calls are not part of local tests.
