# CRM MVP for Telegram Lead Processing

## Goal

Build a simple but scalable MVP CRM for processing Telegram chats, assigning leads to managers, tracking response speed, and getting basic analytics.

The system is intended to replace the current CRM with a product tailored to internal workflows.

## Current MVP Scope

This version includes only the core functionality needed to launch quickly and validate the architecture:

- projects
- users and roles
- chats
- messages
- unread / unanswered logic
- red chats (late response)
- manager assignment
- lead statuses
- tags
- action history (audit log)
- response time metrics
- simple daily statistics
- basic alerts

## Main Principles

- keep the MVP small
- build for future expansion
- avoid unnecessary complexity
- separate business logic from transport and storage layers
- keep the architecture modular

## Suggested Tech Stack

- Backend: FastAPI
- Database: PostgreSQL
- Cache / queue preparation: Redis
- ORM: SQLAlchemy
- Migrations: Alembic
- Local environment: Docker Compose

## High-Level Architecture

The MVP should be organized into clear layers:

- API layer
- service layer
- repository/data access layer
- database models
- background tasks / workers
- configuration/core utilities

Layering sanity check:

```bash
python scripts/check_backend_layers.py
```

## Core Entities

- Project
- User
- Role
- Chat
- Message
- Lead
- Lead Status
- Tag
- Assignment
- Audit Log
- Alert
- Daily Stats

## Projects Domain

Project is the top-level CRM scope for current and future product areas:
Bots, Tracking Links, Chats, Funnels, and Analytics.

This step defines the Project CRUD surface and archive semantics. It does not
change existing bot, chat, lead, or tracking behavior. In the current codebase
`Bot` already has a `project_id`; this step leaves that relationship untouched.

Manual smoke check:

```bash
python scripts/check_backend_layers.py
```

## Bot Project Scope

Every bot belongs to a project via `bots.project_id`. New project-scoped API
surfaces should accept an explicit `project_id` where the caller is selecting
project data. Existing bot endpoints keep backwards compatibility: `GET /bots`
without a query parameter still resolves the authenticated user's project,
while `GET /bots?project_id=<id>` filters by the selected project.

The frontend will later move this selection into a global ProjectSelector and
BotSelector.

## Non-Goals for MVP

The following are intentionally excluded from this phase:

- GPT features
- bot builder
- A/B testing
- postback integrations
- partner cabinet
- advanced analytics
- affiliate tracking logic
- complex automations

## Development Approach

1. design architecture
2. design database
3. create project skeleton
4. implement core entities
5. implement chat/message flows
6. implement assignment and statuses
7. implement metrics and alerts
8. test and stabilize

## Success Criteria

The MVP is successful if:

- chats and messages are stored correctly
- managers can work with chats
- red chats are visible
- lead statuses are tracked
- response time metrics are calculated
- daily stats are available
- the codebase is clean enough to expand later

## Important Constraint

Do not overbuild the first version.
The priority is a stable core, not a feature-rich system.

## Dev Deploy

Dev server deploy is handled by `./deploy-dev.sh` from `/opt/crm-mvp-dev`.
The script now treats frontend build as a required deploy step:

```bash
./deploy-dev.sh
```

Frontend deploy rules:

- the script resets the server checkout to `origin/dev`;
- backend containers are rebuilt with Docker Compose;
- frontend is built with host `node/npm` when available;
- if host `node/npm` is absent, the script builds with `node:20-alpine`;
- `npm ci --include=dev` and `npm run build` must pass, otherwise deploy fails;
- `frontend/dist/index.html` and hashed JS/CSS assets are printed after build;
- nginx is reloaded when available, otherwise fresh static files are updated in place.

Fresh frontend verification:

```bash
curl -fsS http://<dev-host>/ | rg 'assets/index-.*\\.(js|css)'
curl -fsS http://<dev-host>/api/v1/health
```

Do not accept a deploy where frontend build is skipped silently.
