# Tracking audit: 13 October 2026

Source: `download_84a69333-0c57-42e3-8e48-de5b76360d3b.sql.gz`.
Restored in an isolated disposable PostgreSQL with networking disabled. Original
backup unchanged. Last retained message: 2026-10-13 10:12:54 UTC (13:12:54 MSK).
The snapshot has 32,216 chats and 414,698 messages, schema revision 0084.
No customer names, phones, credentials or message contents are included here.

## Chats versus first starts

| Project | Visible chats | First project starts | Chats without /start | Duplicate start chats |
| --- | ---: | ---: | ---: | ---: |
| Вакансии | 13,416 | 9,351 | 0 | 4,065 |
| Ру инвест | 13,261 | 10,871 | 2,285 | 105 |
| Алинка | 2,456 | 1,133 | 1,321 | 2 |
| Латам Гембл | 2,151 | 1,591 | 549 | 11 |
| Узб Гембл | 914 | 478 | 435 | 1 |

Visible excludes soft-deleted/reset chats. A physical chat belongs to a bot or
named account, not to a unique project-wide person. First starts deduplicate
Telegram IDs across ALL project bots and retained history, before applying
report filters. Same-time starts use message UUID as a stable tie-breaker.
Different projects stay independent; missing IDs use chat identity.

Most chats without /start have a valid explanation:

| Project | Channel auto-start without /start | Named-account chats without /start | Other chats without /start |
| --- | ---: | ---: | ---: |
| Ру инвест | 1,860 | 422 | 3 |
| Алинка | 873 | 446 | 2 |
| Латам Гембл | 541 | 0 | 8 |
| Узб Гембл | 311 | 119 | 5 |

Therefore the physical-chat and first-/start counts must NOT be forced equal.
The explicitly requested project-wide duplicate rule is preserved.

## VIP and daily counters

Вакансии uses tag qualification; its selected tag ID resolves correctly to VIP.
There are 238 active VIP leads. None was acquired on 13 October (UTC or MSK).
These 238 cards represent 232 Telegram people: six additional VIP cards are
duplicates across bots. Target-lead metrics still count cards, unlike first
starts. Changing qualification to people and first-source attribution changes
conversion/CPL. The user explicitly confirmed keeping card-based target-lead
counting. No cards or tags were merged or deleted.
30 first qualified by the target tag on 13 October. These are older arrivals.
The old daily header counted 2,812 chats with any /start that day, while canonical
first-project starts are 1,627. This was a genuine cross-surface inconsistency.

The header now uses canonical first-start counting, retains the existing
acquisition-date `leads_today` contract, and adds `qualified_today` in tag mode.
Qualification uses the earliest retained matching tag fact/current assignment,
counted once per lead; multiple selected tags do not multiply a lead.
Old removed tags predating tag-history installation cannot be reconstructed.
Header/tracking daily bounds remain UTC; info-bot periods remain MSK as requested.

## Performance

Original first-start query on this copy took approximately 2.7 seconds and made
tens of thousands of nested comparisons. The query is now split into same-chat
and other-chat lookups. Migration 0085 adds a partial covering start-message
index and a project/person chat index, both built concurrently.

Measured full project report for 6–13 October, including 130 links:
- First pre-covering-index run: 16.9 seconds.
- Warm run with final covering index: 1.48 seconds.
- Output unchanged: 9,349 first starts and 238 qualified cohort leads.
- Header with final indexes: approximately 0.07 seconds; daily qualified = 30.

These are local snapshot measurements with different cache warmth, not an SLA
or a controlled 11x production-speed claim. No stale-result cache was added.

## Info-bot delivery

The SQL backup contains no Redis update/delivery ledger or worker log history,
so it cannot prove which historical duplicate occurred. Code inspection found
unsafe resend windows after unknown sendMessage outcomes and lost ownership.
Changes add background lease renewal, owner-fenced delivery checkpoints,
monotonic offsets, and retained completed checkpoints. Private PostgreSQL
delivery/cursor tables survive lost Redis snapshots; send attempts use an atomic
database guard, so competing workers cannot overwrite an in-flight attempt or
move a confirmed checkpoint backwards. Delivery plans expire after seven days;
cursors remain per bot. Plans contain reply text/counts, never bot tokens.
An in-flight send left
unconfirmed by a crash/timeout is NOT sent again automatically. It produces an
operational alert; the user can explicitly request a fresh report if necessary.
Telegram sendMessage has no application idempotency key, so an unconditional
exactly-once delivery guarantee would be dishonest.

Deploy API/front-end/info-bot worker together and run `alembic upgrade head`.
Migration upgrade/downgrade/re-upgrade was exercised on the restored schema.
No production database, bot token, link attribution or funnel execution changed.

## Link-specific stage details

The details modal omitted the link's bot ID. Its funnel catalogue therefore
included the whole project and initially selected the first alphabetical funnel.
The modal now passes the bot ID; step-options also resolves it from link_id,
checks project/buyer ownership, and marks the link's target funnel (or the bot's
active funnel) as preferred. Other historical funnels of the same bot remain
available. A link/funnel bot mismatch returns 422 instead of a misleading report.
Hidden overview requests are cancelled while stage details are open.

Journey SQL had repeated correlated first-funnel and stalled-state checks,
person-string joins that could not use identity indexes, and a second full
history scan just to count related chats. These now use shared history sets,
direct Telegram-ID joins (anonymous chats remain independent), shared count/page
queries, and typed JSONB stage mappings that scan each fact history once.
Project-wide first-person ranking still precedes bot/link/date filters; handoffs,
retained historical duplicates, tag history, MSK bounds and acquisition rules
are unchanged. No statistics cache or data rewrite was introduced.

On the restored copy, the previous stage query exceeded a 90-second statement
timeout. The updated active-funnel report for 6-13 October returned 2,340 people
and 4,203 related chats in approximately 1.0 second after warm-up. A separate
process's first link-specific request took approximately 4.9 seconds (1,593
people, 3,194 related chats). These are local measurements, not a production SLA.
Reached/remaining counts matched the earlier intermediate optimized report;
stalled counts can advance as the clock crosses the configured idle threshold.

Real PostgreSQL regression checks cover target/active-funnel preference,
foreign project/buyer/bot rejection, handoffs, historical versions, tag removal,
MSK dates, pending/manual states, empty pages and anonymous contacts. Front-end
production build passed. Browser-level UI verification was unavailable because
the in-app browser could not open the existing localhost server.
