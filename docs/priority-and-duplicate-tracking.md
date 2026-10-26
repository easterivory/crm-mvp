# Priority chats and duplicate cohorts

## Configuration and behavior

Settings > Project > Priority chats. An admin enables the tab and selects any project tags and/or published funnel steps. Configuration is saved separately with "Save priorities". Existing projects default to disabled; there are no inferred tag names or block numbers.

The workspace is `(any selected current tag OR any selected reached step in the current chat lifecycle) AND unanswered incoming`. Opening or reading the chat does not change membership. A successfully recorded outgoing bot or manager response clears it; a newer incoming message returns it. Scheduled-but-unsent messages do not count as responses. Existing blocked/deleted/reset chat exclusions and project/bot scoping remain in force.

Steps are matched by funnel identity and stable step key across published versions, not ordinal block number. The selector keeps prior-version selections visible. Reaching a similarly named/keyed step in a different funnel does not qualify. Tags remain current-state conditions: removing the last qualifying tag can remove a chat unless it also qualifies by a reached step.

## Duplicate report

Tracking > Intersections and duplicates (also inside link details). The report loads only on expansion and follows project, bot, buyer, link and date filters. It does not change existing starts, leads, conversions, confidence scores or routing.

- Period: creation date of the current active lead card, in UTC. This is not the date of a subsequent message, tag change or duplicate detection.
- Matching: Telegram ID, normalized phone or username, against strictly earlier cards (creation timestamp plus UUID tie-breaker). Multiple matching fields or earlier cards still count the new card once. First cards and future matches do not count as repeat arrivals.
- Within project and other projects are separate, potentially overlapping subsets. The total is their union, not their sum. Cross-project matches consider only projects visible to the requesting user, as in the duplicate warning. Historical matching cards may be deleted, as in the existing identity lookup; current report cards exclude deleted leads and deleted/reset chats.
- Contacts are evaluated as they exist now. This is a reconstruction, not a historical snapshot of what was known on that day. Changing a phone/username or deleting a current card can change historical results.
- Each current card belongs to exactly one currently assigned tracking link, or "No advertising link". Therefore sums over sources including that row equal the overall card totals for identical filters. A buyer filter excludes cards without a matching owned source. No attempt is made to sum pairwise intersections between advertising links or to count unique humans across phone/username identity graphs.
- The heavy query has a local 15-second timeout, restored afterwards. Resource/time-limit errors produce an explicit retry/shorter-period message, not a false zero. Existing tracking requests do not run this query.

## Deployment

Run `alembic upgrade head` before restarting application services. Revision `20261026_0088` adds `projects.priority_chat_rules` with disabled defaults and a five-second DDL lock timeout. No existing funnel definitions or running states are rewritten. Configure and enable the desired projects after deployment.
