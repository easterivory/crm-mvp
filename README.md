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

