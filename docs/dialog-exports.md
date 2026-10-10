# Dialog Exports

Admins and super-admins can export a project's active dialogs from Chats using
the download icon beside Refresh. Export scope is the whole project or one bot /
named account. Optional dates select message timestamps, inclusive UTC days;
they do not filter chat creation dates.

The ZIP contains UTF-8 TXT or JSONL transcript parts plus manifest.json. It
includes stored message history (including edited/deleted flags, replies and
album IDs), attachment metadata, lead status/tags/score/country, current funnel
step and tracking link name/ID. It does not fetch attachment binaries or pending
scheduled messages. Reset/deleted chats are excluded. Contact fields and manager
comment require an explicit checkbox. Message text can still contain personal
data: disabling that checkbox is not anonymization. Never upload an archive to
an external AI without checking permission to process its contents.

Only explicitly selected database columns are exported. Raw Telegram payloads,
tokens, session strings, access hashes and private file paths are not included.
This is not a database backup or a transactionally consistent point-in-time
snapshot: messages created after request time are excluded, but edits/tags made
during generation may be reflected.

## Deployment

Rebuild the frontend and API and start the new `exports` Compose service:

```sh
docker compose up -d --build api exports
```

Also rebuild/restart `mtproto` to enable larger avatar previews for named
accounts. No migration or new dependency is required. The export service runs
one job at a time in its own ARQ queue, separate from funnel jobs, with a small
database pool. Do not scale this service independently: storage quota checks
assume one archive writer. API and exports must mount the same existing
chat_attachments_data volume. In custom installations, run
`arq app.workers.dialog_export_worker.WorkerSettings` with the same Redis,
database and CHAT_ATTACHMENT_STORAGE_PATH as API.

Defaults: archive expiry 24 hours, transcript limit 500 MiB, total ZIP storage
2 GiB, each transcript part approximately 20 MiB (split at message boundaries).
Configured through DIALOG_EXPORT_MAX_MB, DIALOG_EXPORT_STORAGE_MAX_MB and
DIALOG_EXPORT_PART_MB. Quota/disk pressure fails explicitly; narrow scope or dates
instead of silently truncating. Expired files are cleaned hourly and before new
generation. Cancellation removes the partial archive. A browser download uses
a single-use 60-second ticket, with permissions checked again at download time.
New exports are rejected explicitly if the export worker's heartbeat is absent.

Preview avatars are JPEG miniatures up to 512 px / 64 KiB, requested only when
opened, using the same bounded cache as list thumbnails; originals are not kept.
