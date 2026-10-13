# Submission funnel restart after inactivity

An explicit incoming `/start` (including `/start@bot` and start parameters)
can restart a submission project's bot after at least 30 elapsed days without
messages from the client in that bot's chat. Merely reaching that age does not
schedule or execute a restart. Ordinary text, attachments, custom commands,
manager messages and bot messages do not themselves trigger this policy.

The cutoff is evaluated between the stored start-message receipt timestamp
and the preceding user-message timestamp. It does not use the already-updated
chat timestamp, and a following reply does not hide the gap. Retained deleted
user messages still count as activity. No preceding user message means this is
not an inactivity restart. Recent starts therefore also restart the idle clock.

Only active submission projects and Bot API messages qualify. Gambling projects,
named accounts and imported chats retain their existing behavior. The bot must
have an active published funnel; this policy does not select a draft or switch
to the legacy engine. Delayed commands cannot reset a newer entered step.

When eligible, the existing runtime and its pending/running jobs are cancelled,
job history is retained with safely detached state references, and a fresh
runtime starts at the default trigger of the currently active published funnel.
Old link target-step overrides do not skip the beginning of this restart.
Loaded jobs carrying an old state ID are rejected even when funnel version and
step IDs are unchanged. Legacy jobs with no state ID retain their compatibility.

The chat, lead card, status, tags, contact fields, comments, attribution and
message history are not reset or duplicated. The new run's push counter/visit
markers start fresh; ordinary repeated starts within 30 days keep the earlier
same-step push behavior. Manager assignment follows the existing incoming-message
lease rules. The explicit inactivity restart can leave an old manager pause.

The restart is recorded in chat history and server logs. Fast replies following
the command are preserved until a delayed first prompt is ready. Actual replies
on no-reply timer steps are processed immediately, not held until that timer.
First-project-start statistics remain deduplicated; a returning person is not
counted as a newly acquired person or a second lead card.

No new migration, dependencies, public API fields or UI controls are required
by this change. The preceding push update still requires migration 0086 when
deploying the combined update. Update API and funnel workers together.

Real PostgreSQL regression scenarios cover exact 30-day eligibility, shorter
inactivity, recent ordinary activity, paused/completed/active funnels, same-version
restarts, imported and gambling exclusions, retained deleted input, old pending
and running jobs, retained card/history/tags, duplicate processing, first-start
counting and a following phone answer across a delayed prompt. No live Telegram
send or production-data modification was performed for verification.
Final backend suite: 780 passed, 2 skipped, 7 subtests passed. Compilation and
diff whitespace checks passed; frontend code was not changed.
