# Assignment and manual funnel takeover

Opening an unassigned chat as a Manager still assigns its lead and starts the
existing assignment lease. Assignment, reassignment and removal no longer pause
the funnel or cancel its pending jobs. Viewing or drafting an answer does not
change automation state. A successfully delivered manual CRM reply pauses the
funnel and cancels its pending jobs. This applies to text, media, snippets and
photo albums, including manually scheduled replies at delivery time. Scheduling
alone does not pause anything; failed deliveries do not trigger a pause.

Historical imports and automated bot/broadcast messages do not trigger this
rule. The reply pause audit contains `reason=manager_reply` and the CRM message
ID. Existing pauses remain unchanged and additional replies do not create
duplicate pause events. Sidebar status refreshes when the chat lifecycle changes.

The lead sidebar exposes an explicit takeover button for an active funnel.
`POST /api/v1/chats/{chat_id}/funnel-pause?project_id=...` requires project access.
A Manager must own the lead; Admin, Super Admin and Operator may also take over.
Buyers cannot use this endpoint. Repeated requests are idempotent.

Takeover pauses the current state and cancels pending funnel jobs in the request
transaction. It preserves the current step, collected answers and waiting state.
An audit entry contains the actor, step and `reason=manager_takeover`; a visible
chat event records the takeover. A delivery already sent to Telegram cannot be
recalled by pausing. The existing worker checks remain responsible for jobs
already claimed by a worker.

The existing resume endpoints and sidebar step selection remain unchanged.
Manual review, user-block and external Telegram account pauses are unchanged.
Existing paused chats are NOT resumed automatically on deployment: review them
and use the existing resume controls intentionally.

No schema migration, new dependency or additional background timer is required.
Deploy API and frontend together. Verify that opening/assigning a test chat leaves
its funnel active, explicit takeover pauses it with an audit event, and selecting
a resume step continues the existing scenario.
