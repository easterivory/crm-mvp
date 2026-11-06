# Automatic Telegram Formatting

## Scope

Author-entered funnel messages/prompts, broadcasts and advertising slots recognize
supported Telegram HTML without the former editor checkbox. The editor toolbar
is always available. The phone preview renders bold text, links, etc. for both
text messages and media captions, including saved content with `parse_mode: null`.

Mode resolution happens on the author template BEFORE lead values are inserted.
The low-level Telegram sender remains explicit: lead messages, manager chat
messages, AI output and values inserted by templates are not automatically
interpreted as HTML. Plain text without supported tags stays plain text.

Malformed HTML is rejected during broadcast/slot save and funnel publication.
The editor shows a warning rather than silently repairing invalid links or
crossing tags. HTML-escaped tags are not recursively decoded. To display literal
tags inside HTML, escape them (`&lt;b&gt;`) instead of using raw `<b>`.

## Existing Advertising Queues

No migration or bulk update is needed for this formatting change. A saved slot
with valid HTML and `parse_mode: null` is normalized in memory before its next
send. Saving an edited slot persists the effective mode with the usual revision
check. Existing slot IDs, queue composition, timers and delivery claims are not
changed. Sent posts are not edited or resent. Historical content snapshots are
not rewritten.

Rebuild the main CRM frontend and update API and all sending workers from the
same checkout. Follow the normal main-server deployment procedure. Do not deploy
the separate `postback_gateway/` artifact as part of this change. Other pending
changes in the release may have their own migration requirements.

## Verification

- Backend formatting tests exercise text and photo requests, UTF-16 entities,
  legacy null-mode content, persistence, malformed/unsafe URLs and template safety.
- A real isolated PostgreSQL advertising test verifies one formatted delivery,
  unchanged legacy slot/snapshot/revision, and the remaining queue left pending.
- Existing advertising scenarios, concurrency and broadcast delivery tests cover
  normal revision, audience protection and duplicate-send behavior.
- Browser fixture `frontend/tests/run-telegram-formatting.mjs` checks desktop and
  mobile previews, legacy text/photo slots, toolbar escaping and invalid markup.
  Use `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH` and `CRM_UI_TEST_URL` for local tooling.
- The supplied 5 November backup was read only. All nine advertising slots were
  compiled locally without Telegram requests: the three affected slots resolve
  to HTML with valid formatting/link entities; the plain-text slot stays plain.

Tests do not send real Telegram messages. Production data and queues are not
modified by these checks.

Local verification on 5 November 2026: 1022 backend tests passed, 5 environment-
dependent checks skipped, 7 subtests passed. Eight frontend control tests passed;
the browser checks passed at 390px and 1440px. The TypeScript/production frontend
build and `git diff --check` passed. PostgreSQL/Redis were disposable loopback
test services, not the production database. Existing dependency/chunk-size and
ORM metadata warnings remain; Docker runtime was not exercised in this run.
