# Chat avatars

The chat list and conversation header lazy-load authenticated thumbnails through
`GET /api/v1/chats/{chat_id}/avatar?project_id=...`. The route checks project scope
and active chat ownership, without marking read, assignment or funnel actions.
It never returns Telegram credentials or Telegram file URLs.

Bot API retrieves the smallest current user profile photo. MTProto retrieves
the small profile photo via a separate avatar RPC queue, not the outgoing-message
queue. The account worker needs the same release as the API. The cosmetic queue
is capped at 256 pending requests even when the worker is offline. Privacy
restrictions, missing photos, offline workers and cache failures leave initials visible.

Only a metadata-free JPEG of at most 128x128 pixels / 64 KiB is retained.
Original files are not stored. Pillow and SQLite are already available; no new
dependencies or PostgreSQL migration are needed.

`CHAT_AVATAR_STORAGE_PATH` defaults to `storage/chat_avatars`. Its disposable
SQLite cache has a 200 MiB database-file ceiling and at most 10,000 entries by
default. Least recently accessed entries are evicted; entries unused for 30 days
are removed on cache access/write. Freed pages are reused, not accumulated.
Temporary SQLite rollback journals may use additional space during a write.
Keep this directory on local/shared-host storage, not network filesystems.
Deleting it loses only cached images, never CRM data.

`CHAT_AVATAR_CACHE_MAX_MB`, `CHAT_AVATAR_CACHE_MAX_ENTRIES` and
`CHAT_AVATAR_CACHE_SECONDS` configure limits; refresh defaults to once a day.
Negative photo results are cached too. Transient errors retry after five minutes.
Stale photos are served immediately while an authenticated request schedules
a refresh with a fresh database session. No PostgreSQL transaction spans Telegram
downloads. Redis locks prevent duplicate refreshes across API processes.

The UI limits downloads to four concurrent requests and visible rows. Blob URLs
are released on unmount. Browser responses are private, cached for one hour
(five minutes for an absent photo), and vary by Authorization. Polling chat data
does not remount/reload avatars.

Run `tests/test_chat_avatars.py`; the scope/state test also requires an isolated
PostgreSQL via `CRM_TEST_POSTGRES_URL`. Real profile-photo retrieval needs a live
test bot and authorized work account. Test both, private/missing photos, scrolling,
project switching and the offline-account fallback after deployment.
