# Chat photo albums and shared cancellation

Any manager/operator with message-write access to a project can cancel a pending
scheduled message in that project's chat, regardless of its author. Buyers and
users outside the project remain denied. The author of the scheduled message is
not changed. Sent/running messages cannot be cancelled. Cancellation is logged
with the actor ID.

The worker atomically claims each pending message before delivery. A cancellation
and a worker claim cannot both succeed. No batch-wide row locks span Telegram I/O.
The running state is committed before external delivery; ambiguous delivery
failures are not automatically retried, to avoid duplicate messages.

The composer supports selecting/dropping/pasting 2-10 photos as one Telegram
album, with a shared caption and optional reply for immediate delivery. Preview
photos can be removed individually. Single attachments use the existing routes.
Telegram stores an album as multiple messages with a shared media_group_id; CRM
retains each message and its media individually, preserving history and replies.

New multipart routes (repeated `files` field):

- POST /api/v1/chats/{chat_id}/messages/album
- POST /api/v1/chats/{chat_id}/scheduled-messages/album

Only valid, nonanimated JPEG/PNG/WebP photos are accepted; count, file size,
dimensions, aspect ratio and caption length are checked before delivery. WebP
is converted to JPEG, and filenames/mime types are normalized so MTProto does
not accidentally send photos as documents. Bot API uses sendMediaGroup; named
accounts use one Telethon send_file call with a list. Each successful account
photo is preserved via the existing account media storage path.

Scheduled albums persist in the optional scheduled_messages.album_files JSONB
column (migration 20261010_0081). Old rows keep NULL and use existing single-file
logic. API responses expose only album_count, never private storage paths.
Pending files are removed after cancellation or successful delivery.

Deployment: apply `alembic upgrade head`, then update API, scheduled-message
worker, Telegram-account worker and frontend together before using albums.
No new dependencies. Cancel outstanding scheduled albums before downgrading;
downgrade removes the new album metadata column, not legacy scheduled messages.

Tests use real Pillow, multipart serialization and isolated PostgreSQL, including
cross-manager permissions, denied roles/projects, claim/cancel races and migration
upgrade/downgrade with legacy data. Local UI acceptance covers preview/removal,
mobile layout, real API scheduling and cancellation by a second manager. Actual
delivery must also be checked with a live bot and authorized work account.
