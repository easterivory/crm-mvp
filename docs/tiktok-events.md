# TikTok advertising events

## Deployment and setup

1. Back up the database. Apply `alembic upgrade head` (new revision `20261011_0082`) before starting the updated API and jobs worker. Existing tracking links have no TikTok integration and keep their previous behavior.
2. Open Tracking, find the advertising link, and click **TikTok**. Set its TikTok Pixel ID and Events API Access Token, enable delivery, and save. An admin can configure project links; a buyer can configure only their own links.
3. Use an existing landing attached to that link, or create one in the same window. The URL in the TikTok ad must lead to this landing, not directly to Telegram, to preserve the individual `ttclid`.
4. Configure the event rows independently of Meta: enable/disable, event name, and tag/status/funnel triggers. Registration and first deposit default to `CompleteRegistration` and `Purchase`; redeposits are separate `Purchase` occurrences. Canonical registration/deposit events from manual actions, funnels and partner postbacks use the same pipeline. Tag/status-only mappings fire only on their configured trigger.
5. For testing, enter TikTok's Test Event Code, perform an actual ad-to-landing-to-Telegram journey, and inspect the delivery log and TikTok Test Events. Remove the test code before live traffic. Verify the pixel/dataset is attached to the ad group and the conversion is within its attribution window.

## Delivery and attribution

- The landing installs TikTok Pixel. Browser and server landing events share the same event name and event ID for deduplication. Telegram starts, contacts, channel membership and CRM events are delivered by Events API.
- `ttclid`, `_ttp`, landing URL, browser user agent and client IP follow the existing landing bridge. For channel traffic they are saved in the per-visit invite/subscription and copied into the lead when its funnel starts. Old contexts containing `ttclid` only in the original landing URL are also recognized.
- A direct Telegram link cannot supply a TikTok click ID. Events can still be sent with available matching data, but acceptance by Events Manager does not guarantee attribution in Ads Manager. The CRM log explicitly shows whether a click ID was available.
- Credentials are encrypted with the existing credential encryption service (`AI_CREDENTIAL_ENCRYPTION_KEY`, falling back to `SECRET_KEY`). Keep that key stable and include it in the secure restore procedure. API responses and browser markup never expose the access token.
- Each event is inserted into a PostgreSQL outbox in the originating transaction. A rollback removes it. Unique event IDs prevent concurrent duplicates. ARQ's jobs worker drains committed rows every 15 seconds; claims are committed before HTTPS calls, so Telegram/CRM transactions do not wait on TikTok network IO.
- Timeouts, rate limits and temporary provider failures retry with backoff. A stale in-flight claim becomes eligible after three minutes. Permanent failures are visible in the log and can be retried after correcting settings. Event time and ID are preserved. Events older than seven days are not assigned a false new conversion time.
- Registration and first deposit deduplicate within a lead lifecycle. Separate canonical redeposit events retain their identity. Tag/status rules deduplicate within the lifecycle, matching the existing CRM rule semantics.
- Telegram button clicks default to the custom event `TelegramClick`, while a real bot start uses standard `Contact`. They intentionally do not both emit `Contact`, which would inflate that conversion count. Event names remain configurable.
- Delivery rows are retained for 30 days, with indexed and bounded cleanup. Logs show the latest 50 events, status, attempt count, provider request ID and click-ID availability, without raw matching data or credentials.

## Verification

Automated coverage uses real PostgreSQL for opt-in behavior, credential preservation, owner/project boundaries, buyer landing creation, transactional rollback, concurrent deduplication, canonical events and retries. Meta's existing tests remain unchanged. A real TikTok ad-account end-to-end test requires the account's credentials and an actual ad click; local automated checks do not claim to replace it.

Migration 0082 upgrade/downgrade is verified on the current schema. The repository also has a pre-existing empty-database bootstrap issue in migration 0012 (duplicate `waiting_for_answer`); this integration does not alter historical migrations.
