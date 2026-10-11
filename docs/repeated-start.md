# Repeated Telegram start

A repeated `/start` is an engagement event for an active published funnel,
not a new lifecycle. The restart indicator and chat audit note are retained.
It does not emit another advertising bot-start conversion.

When a message step waits for interaction, `/start` continues along its
default Next edge. It never guesses a button-specific branch or supplies a
required field value. Input steps still require their actual answer. Manager
pauses, completed funnels and imported dialogs are not restarted.

Debounced input is split at command boundaries and processed in arrival order.
The command is not combined with name/phone answers. Replies following an
engagement transition remain unprocessed when the next step has a scheduled
delay. The user-input worker commits the transition before retrying at the
scheduled time; retries do not process the same command twice.

Legacy BotEngine repeat-start behavior is unchanged. No schema migration or
existing funnel configuration change is needed.

Regression coverage: `tests/test_repeated_start.py` uses an isolated PostgreSQL
schema and Redis, including real webhook intake, delayed input delivery,
duplicate processing, required fields, button-only branches and manager pauses.
Set `CRM_TEST_POSTGRES_URL`, `REDIS_URL` to disposable instances before running.
