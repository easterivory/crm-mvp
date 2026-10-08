# Disappearing bot-funnel screens

Enable `disappear_after_next: true` on each message that should disappear.
The constructor exposes this checkbox separately for every sequence item.
Missing/false values preserve existing behavior. No migration is needed.

This is send-before-delete, not editing a Telegram message in place:
the next delivered funnel message can have different text, media and buttons.
Only after its successful delivery is the marked bot message deleted.
The final screen remains until another funnel message is delivered.
Delays and typing keep the old screen visible until the next message arrives.
Automatic transitions also replace marked screens. Several marked messages
in one block replace one another in order.

The marker is stored in the existing funnel runtime JSON, survives worker
restarts and transitions, and is removed on normal funnel-state reset.
Cleanup also checks chat ownership, bot sender, current chat cycle and age.
User/manager messages are never selected. Account transport is not changed.

Telegram limits deletion to messages less than 48 hours old. Expired screens
are retained. A deletion refusal is logged and does not retry a successfully
delivered step. A transient deletion failure can leave the old screen visible;
there is no promise of eventual cleanup in that case. Database history retains
the content of successfully removed screens with a deletion timestamp; these
tombstones are excluded from funnel input queries.

Only an interaction that actually advances the funnel can replace a screen:
opening a URL button does not notify the bot, and query buttons require the
user to send the prepared text. Callback buttons use existing routing and
stale-callback protection without changes.

## Verification

Run `tests/test_funnel_disappearing_messages.py` against an isolated PostgreSQL
using `CRM_TEST_POSTGRES_URL`. No Telegram responses are substituted.
These tests cover configuration defaults, marker persistence, cross-chat and
sender protection, reset/age guards, real missing-token refusal and history.
The regression test also reproduces cycle-field expiration after the real chat
timestamp update, checks fully expired chat objects, and runs with and without
transaction release before Telegram. Lifecycle checks use explicit async SQL;
cleanup never implicitly loads attributes from an expired chat object.

Before release, use a test bot with a published three-screen funnel:
photo + two inline branches -> different photo/text/buttons -> final text.
Check both branches and Back, delayed delivery and the auto-transition timer.
The clicked old screen must disappear only after its replacement arrives.
Verify CRM retains the removed screen, old buttons cannot route stale steps,
and disabling the checkbox restores separate messages. Real Telegram deletion
requires this live-bot check; local database tests do not confirm remote UI.
