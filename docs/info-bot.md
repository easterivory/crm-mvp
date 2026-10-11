# Super-admin tracking info bot

## Setup and rollout

- Deploy the API, frontend and shared worker (`python -m app.workers all`). The shared worker includes the new polling loop; alternatively run `python -m app.workers info` separately. Redis prevents two instances from polling the same info bot concurrently.
- No database migration or new dependency is required. Configuration is an opt-in record in `system_settings`; the default is disabled. Existing buyer/admin/backup bots and CRM login keep their existing tokens and behavior.
- Create a separate bot in BotFather. In CRM open Settings > System > Admin Telegram Bot > Info bot statistics, enter its token, enable it and press the separate save button. The API validates the token through Telegram before storing it. Do not reuse a bot already attached to CRM, buyer statistics, admin login or backups.
- Set the CRM super-admin user's Telegram ID in the team profile. Open the info bot and send `/stats`. Other roles, deleted users and group chats have no access. Permissions are checked on every message and button press.
- The token is encrypted with the existing credential encryption service. Keep `AI_CREDENTIAL_ENCRYPTION_KEY` / its existing `SECRET_KEY` fallback stable for restore. UI/API responses expose only the username and whether a token exists.

## Reports

- Select a project, then use the bot and link menus. Lists are paginated. Archived (not deleted) projects can still be inspected.
- Current and previous weeks are Monday through Sunday. Months are calendar months. Previous/next period buttons allow navigation; future periods are not selectable. Custom dates are entered as `DD.MM.YYYY DD.MM.YYYY`, inclusively. All boundaries use Europe/Moscow.
- Send a tracking Telegram URL with `start`, a channel invite, a `/join/code` URL, or an attached landing URL. Both `t.me` and `telegram.me` are recognized. One message can contain up to 20 links, separated by spaces or newlines. Duplicate references to the same CRM link are counted only once. The bot responds for the current week and all time, separately for each link and with a combined total; unrecognized inputs are reported explicitly.
- Subscribers are confirmed channel joins, not pending requests, bot starts or the current Telegram channel member counter. Leads use the project's tracking lead status configuration and the same lifecycle filters as CRM tracking. Starts retain CRM's first-start-per-person-per-project deduplication. Registration/FD/RD use the existing canonical event aggregation.
- Reports include joins, leads, starts, clicks, join requests, leaves, submissions for submission projects, registration/FD/RD, spend, CPL and acquisition-to-lead conversion. Combined totals sum link metrics, not unique people across different links/projects. Moscow date bounds may intentionally differ from the existing CRM's UTC day bounds near midnight; the existing CRM calculations were not changed.
- All-time queries aggregate directly and do not allocate a daily series starting in 1970. Sessions close before Telegram sending. Redis stores menus and polling offsets; repeated report calculation failures are bounded to avoid permanently blocking the bot.

## Production check

1. Enable a new separate token and open the returned Telegram username.
2. Check that a linked super-admin can view multiple projects; an admin/buyer cannot.
3. Send a bot link, a channel invite, a landing link and a list containing duplicate links plus one invalid link.
4. Check week/month/custom/all-time periods, including events around 00:00 Moscow.
5. Remove the user's super-admin role and confirm that an old inline button no longer returns statistics.
6. Confirm the existing admin-login bot, buyer bot and backup bot still work independently.

Local tests use real PostgreSQL and Redis. A live Telegram delivery test requires the new bot token; no mock transport or fabricated successful Telegram delivery is used.
