# Project Scope — MVP Only

## Purpose

Build the first working version of an internal CRM for Telegram lead processing.

---

## Chat vs Lead (важно)

- Chat — это Telegram-диалог
- Lead — бизнес-сущность, привязанная к Chat

Правила:

- 1 Chat = 1 Lead (в MVP)
- Lead хранит:
  - статус
  - менеджера
  - теги
- Chat хранит:
  - сообщения
  - unread / unanswered

Не смешивать эти сущности.

---

## Multi-project

Все ключевые сущности должны иметь project_id.

---

## Users / Roles

- super_admin
- admin
- manager

---

## Chats

- список чатов
- фильтры
- поиск
- unread
- unanswered
- red chats

---

## Chat ordering priority

Сортировка:

1. red chats
2. unanswered
3. latest activity

---

## Messages

- входящие
- исходящие
- timestamps
- sender_type (user / manager / system)

---

## Lead

- связан с Chat
- статусы
- теги
- менеджер

Статусы:

- new
- in_progress
- qualified
- lost

---

## Assignment

- менеджер привязан к Lead
- 1 lead = 1 менеджер
- все изменения логируются

---

## Audit log

Хранить:

- действие
- кто сделал
- когда
- над какой сущностью

---

## SLA

- first response time
- average response time
- red chat (по таймеру)

---

## Alerts (минимум)

- долгий ответ
- много необработанных

---

## Daily stats

- новые чаты
- обработанные
- квалифицированные
- потерянные
- среднее время ответа

---

## Исключено

- GPT
- боты
- A/B
- постбеки
- сложная аналитика

