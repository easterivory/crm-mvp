# Technical Requirements

## Stack

- FastAPI
- PostgreSQL
- Redis
- SQLAlchemy
- Alembic
- Docker

---

## Architecture

Слои:

- api
- services
- repositories
- models

---

## External identifiers

Chats must store:

- external_chat_id (Telegram chat id)
- external_user_id

Индексы обязательны.

---

## Database rules

### Основные таблицы

- users
- roles
- projects
- chats
- messages
- leads
- lead_statuses
- tags
- assignments
- audit_logs
- alerts
- daily_stats

---

## Uniqueness

- external_chat_id уникален в рамках project
- 1 lead на chat

---

## Message model

Обязательные поля:

- sender_type: user / manager / system

---

## Response time logic

First response:

- от первого сообщения пользователя до ответа менеджера

Average:

- среднее время ответа

Unanswered:

- последнее сообщение от пользователя

Red:

- превышен таймер

---

## Pagination

Все списки:

- limit
- offset

---

## Soft delete

- is_deleted или archived_at
- не удалять критичные данные

---

## Time

- все в UTC

---

## Indexes

Обязательно:

- external_chat_id
- external_user_id
- project_id
- manager_id
- status_id
- created_at

---

## API

- REST
- /api/v1
- CRUD:
  - chats
  - messages
  - leads
  - tags
  - assignments

---

## Health endpoint

GET /health:

- db status
- redis status
- api status

---

## Logging

- errors
- audit logs

---

## Redis

Использовать для:

- будущих очередей
- алертов

