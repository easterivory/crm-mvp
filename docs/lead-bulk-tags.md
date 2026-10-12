# Lead card tag editing

In the chat's lead card, select/deselect tags with checkboxes and apply with
`Сохранить изменения`. Search does not reset the selected changes. Cancel
discards only local pending changes. The list loads all project tag pages,
not just the first 100 tags. Individual badge removal remains available when
there are no pending bulk changes.

`PATCH /api/v1/tags/leads/{lead_id}/tags?project_id=...` accepts:

```json
{"add_tag_ids": [], "remove_tag_ids": []}
```

Each list is limited to 100 UUIDs; overlapping add/remove IDs are rejected.
The endpoint validates every tag's project before writing and applies the
delta in a savepoint with a lead row lock. It does not replace unrelated tags
assigned by other managers. Existing single-tag routes remain unchanged.

New additions use the existing advertising/lifecycle event pipeline; replayed
additions do not retrigger it. Confidence/routing is recalculated once on the
final set, preventing intermediate tag states from triggering VIP routing.

The card remains mounted during refresh, preserving scroll. Tag refreshes
do not reset unsaved contact/comment drafts. Responses for a previous chat
are ignored after switching to another chat.

Verification: real PostgreSQL tests cover prevalidation/atomicity, project
isolation, deduplication, lifecycle triggers and legacy routes. Browser
checks cover multiple additions/removals, tags beyond the first page, single
removal, scroll preservation and unsaved contact fields. No migration needed.
