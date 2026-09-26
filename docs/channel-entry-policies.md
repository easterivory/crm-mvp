# Channel entry policies

Deploy migration `20260926_0078` before restarting API, worker and jobs. Rebuild
the frontend. Both new channel flags default to false and preserve existing
campaign settings and channel tracking counters. Downgrade removes only these
flags. Existing channel events are not replayed when a setting is enabled.

Super admins configure each channel in Settings / Landers and domains / Channels:

- `restart_funnel_on_rejoin`: a new entry after a recorded earlier membership may
  cancel pending funnel tasks and replace the existing funnel state. The current
  published tracker funnel starts again; the chat and history are retained.
  For join requests, the existing global auto-start setting still applies.
- `start_funnel_on_direct_join`: confirmed membership without a join request can
  start the funnel. Conservatively requires a non-deleted, non-blocked private
  identity with a recorded incoming user message. This does not grant Telegram
  messaging permission; Telegram can still reject delivery. Unknown users are
  skipped with a stored reason, never reported as successfully started.

After an explicit CRM reset, a new eligible entry reactivates the same chat,
clears leftover funnel state and cancels old pending tasks without needing the
restart flag. Soft-deleted chats are not restored automatically.

Join confirmations that belong to a request do not trigger a second start.
Processing is serialized by tracker bot and Telegram user using Redis. Restart
application is checkpointed on the event, so retries do not reset it again.
Outcome and skip/error reasons are retained on the event and exposed by the
existing channel events API, and logged with event/chat identifiers.

Verification before production use:
1. Defaults: repeat request does not restart an existing funnel.
2. Reset a test chat, leave, submit a new request: one chat, new funnel start.
3. Enable rejoin restart, leave/rejoin: current scenario restarts once.
4. Enable direct entry: previously contacted bot user starts; unknown user skips.
5. Request followed by member update, retries and concurrent recovery: no double start.

Tests: `python -m pytest tests/test_channel_tracking.py tests/test_channel_entry_policies.py tests/test_channel_reset_sqlite.py`.
The SQLite integration tests additionally require `aiosqlite`. Migration round
trip is tested on SQLite; a PostgreSQL migration and live Telegram delivery need
verification on staging before deployment.
