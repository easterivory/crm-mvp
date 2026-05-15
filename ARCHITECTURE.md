# System Architecture — CRM MVP

> Единственный источник правды: README.md, PROJECT_SCOPE.md, TECH_REQUIREMENTS.md, DO_NOT_BUILD_YET.md
> Версия: с правками от 2026-04-22

---

## Внесённые изменения

| # | Правка |
|---|--------|
| 1 | Сервисы могут вызывать друг друга (с явным графом зависимостей) |
| 2 | `is_red` убран из хранилища — вычисляется на лету |
| 3 | В Chat добавлены `last_user_message_at` и `last_manager_reply_at` |
| 4 | Assignment упрощён — `manager_id` хранится прямо в Lead |

---

## 1. Архитектура системы — слои

```
┌──────────────────────────────────────────────┐
│         API Layer  (FastAPI routers)          │  ← HTTP, валидация, auth
├──────────────────────────────────────────────┤
│         Service Layer                         │  ← бизнес-логика
│  (сервисы могут вызывать друг друга)          │
├──────────────────────────────────────────────┤
│         Repository Layer                      │  ← только SQL, без логики
├──────────────────────────────────────────────┤
│         Models Layer  (SQLAlchemy ORM)        │  ← таблицы, индексы
├──────────────────────────────────────────────┤
│   PostgreSQL               │      Redis        │  ← инфраструктура
└──────────────────────────────────────────────┘
              ↕  (независимо)
┌──────────────────────────────────────────────┐
│      Workers Layer  (background tasks)        │  ← alert_worker, stats_worker
└──────────────────────────────────────────────┘
              ↕
┌──────────────────────────────────────────────┐
│      Core / Config / Infra utils              │
└──────────────────────────────────────────────┘
```

Правило слоёв:
- API вызывает только Service.
- Service может вызывать другой Service и Repository.
- Repository вызывает только Models (ORM).
- Workers вызывают Services (не Repository напрямую).
- Circular imports запрещены — граф зависимостей между сервисами должен быть ациклическим.

---

## 2. Структура проекта

```
crm-mvp/
│
├── app/
│   ├── main.py                        # точка входа FastAPI, lifespan, роутеры
│   │
│   ├── api/
│   │   └── v1/
│   │       ├── dependencies.py        # DI: db session, current_user, project_id
│   │       └── routers/
│   │           ├── health.py          # GET /health
│   │           ├── projects.py
│   │           ├── users.py
│   │           ├── chats.py
│   │           ├── messages.py
│   │           ├── leads.py
│   │           ├── assignments.py     # PATCH /leads/{id}/manager
│   │           └── tags.py
│   │
│   ├── services/
│   │   ├── chat_service.py            # список, фильтры, сортировка, is_red вычисление
│   │   ├── message_service.py         # приём/запись сообщений → вызывает chat_service
│   │   ├── lead_service.py            # статусы лида → вызывает audit_service
│   │   ├── assignment_service.py      # manager_id в Lead → вызывает audit_service
│   │   ├── audit_service.py           # запись в audit_log (вспомогательный)
│   │   ├── metrics_service.py         # SLA: first/avg response time
│   │   ├── alert_service.py           # проверка условий → вызывает chat_service
│   │   └── stats_service.py           # daily stats → вызывает metrics_service
│   │
│   ├── repositories/
│   │   ├── base.py                    # BaseRepo: get, list (limit/offset), soft delete
│   │   ├── project_repository.py
│   │   ├── user_repository.py
│   │   ├── chat_repository.py         # фильтры по флагам и timestamp-полям
│   │   ├── message_repository.py
│   │   ├── lead_repository.py         # включает manager_id
│   │   ├── audit_repository.py
│   │   ├── alert_repository.py
│   │   └── stats_repository.py
│   │
│   ├── models/
│   │   ├── base.py                    # id (uuid), created_at, is_deleted
│   │   ├── project.py
│   │   ├── user.py
│   │   ├── role.py
│   │   ├── chat.py                    # ↓ подробнее в секции 3
│   │   ├── message.py                 # sender_type: user / manager / system
│   │   ├── lead.py                    # manager_id (FK), status, tags
│   │   ├── tag.py
│   │   ├── audit_log.py
│   │   ├── alert.py
│   │   └── daily_stats.py
│   │
│   ├── schemas/                       # Pydantic request / response
│   │   ├── chat.py                    # ChatOut включает вычисляемый is_red
│   │   ├── message.py
│   │   ├── lead.py
│   │   ├── tag.py
│   │   ├── user.py
│   │   └── stats.py
│   │
│   ├── workers/
│   │   ├── __main__.py                # entrypoint: python -m app.workers [alert|stats]
│   │   ├── alert_worker.py            # периодически проверяет условия алертов
│   │   └── stats_worker.py            # раз в сутки агрегирует daily_stats
│   │                                  # red_chat_worker УДАЛЁН — is_red вычисляется
│   │
│   └── core/
│       ├── config.py                  # ENV, SLA_THRESHOLD_MINUTES
│       ├── database.py                # SQLAlchemy engine, async session factory
│       ├── redis.py                   # Redis клиент (готов к очередям)
│       ├── security.py                # JWT, роли
│       └── constants.py              # LeadStatus enum, SenderType enum, SLA таймер
│
├── alembic/
│   ├── env.py
│   └── versions/
│
├── docker-compose.yml                 # app + postgres + redis
├── Dockerfile
└── requirements.txt
```

---

## 3. Основные модули и их ответственность

### API Layer — `api/v1/routers/`

Принимает HTTP-запрос, валидирует через Pydantic-схему, извлекает `current_user` и `project_id` из DI-контейнера, вызывает один сервис, возвращает ответ. Никакой бизнес-логики. Авторизация проверяется на уровне `dependencies.py`.

---

### `chat_service`

Ответственность:
- Список чатов с фильтрами: unread, unanswered, red.
- Сортировка: red → unanswered → latest activity.
- Вычисление `is_red` на лету: `now(UTC) - last_user_message_at > SLA_THRESHOLD` при условии, что `last_manager_reply_at < last_user_message_at` (или менеджер вообще не отвечал).
- `is_red` **не хранится в БД**. Вычисляется в сервисе при формировании ответа и при сортировке.
- Для сортировки по red при тысячах чатов — вычисление делается на стороне SQL через выражение с timestamp-сравнением, чтобы не тащить все строки в память.

Вызывает: `chat_repository`.

---

### `message_service`

Ответственность:
- Запись входящего / исходящего сообщения.
- Проставление `sender_type` и `message_type`.
- При `sender_type = user`: обновляет `chat.last_user_message_at` и `chat.last_message_at`.
- При `sender_type = manager`: обновляет `chat.last_manager_reply_at` и `chat.last_message_at`.
- `unanswered` и `unread` не хранятся — вычисляются из обновлённых timestamp-полей.

Вызывает: `message_repository`, `chat_service` (обновление timestamp-полей и флагов).

---

### `lead_service`

Ответственность:
- Смена статуса лида: `new → in_progress → qualified / lost`.
- Проверка допустимых переходов статусов.
- 1 Chat = 1 Lead — проверяется при создании.

Вызывает: `lead_repository`, `audit_service`.

---

### `assignment_service`

Ответственность:
- Обновление `lead.manager_id` (единственное место хранения текущего назначения).
- Логирование каждого изменения через `audit_service`.

Отдельная таблица `assignments` **не используется** — текущий менеджер хранится прямо в Lead. История изменений хранится в `audit_log`.

Вызывает: `lead_repository` (обновить manager_id), `audit_service`.

---

### `audit_service`

Ответственность:
- Единственная точка записи в `audit_log`.
- Поля: `action`, `actor_id`, `entity_type`, `entity_id`, `meta (JSON)`, `created_at (UTC)`.
- Вызывается из других сервисов — никогда из API напрямую.

Вызывает: `audit_repository`.

---

### `metrics_service`

Ответственность:
- First response time: `first_manager_reply_at - first_user_message_at` для чата.
- Average response time: среднее по всем парам user-сообщение → manager-ответ.
- Данные читаются из `messages` по `chat_id`.

Вызывает: `message_repository`.

---

### `alert_service`

Ответственность:
- Проверка двух условий: долгий ответ (много red-чатов), много необработанных.
- При срабатывании — создаёт запись в таблице `alerts`.
- Без отправки в Telegram (DO_NOT_BUILD_YET).

Вызывает: `chat_service` (получить количество red/unanswered), `alert_repository`.

---

### `stats_service`

Ответственность:
- Агрегация за сутки: новые / обработанные / квалифицированные / потерянные чаты.
- Среднее время ответа за день (через `metrics_service`).
- Результат пишется в `daily_stats`.

Вызывает: `lead_repository`, `metrics_service`, `stats_repository`.

---

### Repository Layer — `repositories/`

Каждый репозиторий отвечает только за одну таблицу. Реализует:
- `get_by_id`, `list` (с limit/offset), `create`, `update`, `soft_delete`.
- Фильтры передаются как параметры — логика фильтрации не живёт в репозитории.
- `chat_repository` дополнительно поддерживает фильтры по `is_deleted`, `unanswered`, и SQL-выражение для `is_red` через timestamp-сравнение.

---

### Models — ключевые поля

**Chat:**
```
id, project_id, external_chat_id (indexed), external_user_id (indexed),
contact_name (nullable),
last_message_at, last_user_message_at, last_manager_reply_at,
last_read_at (nullable),
updated_at, created_at, is_deleted
```
Вычисляемые (не хранятся):
- `unread`     = last_message_at > last_read_at (или last_read_at IS NULL)
- `unanswered` = last_user_message_at > last_manager_reply_at (или last_manager_reply_at IS NULL)
- `is_red`     = unanswered AND now() - last_user_message_at > project.sla_threshold_minutes

**Lead:**
```
id, project_id, chat_id (unique), manager_id (FK → users, indexed),
status_id (FK → lead_statuses), phone (nullable), username (nullable),
updated_at, created_at, is_deleted
```

**Message:**
```
id, chat_id, external_message_id (nullable, partial unique per chat),
message_type (varchar: text/image/video/audio/file/sticker/system),
sender_type (varchar: user/manager/system),
sender_id (nullable), body (nullable), created_at
```

**AuditLog:**
```
id, project_id, actor_id, action, entity_type, entity_id,
meta (JSONB), created_at
```

---

### Workers — `workers/`

Workers — это отдельный Python entrypoint, запускаемый независимо от API процесса:

```
python -m app.workers        # запустить всех workers
python -m app.workers alert  # запустить только alert_worker
python -m app.workers stats  # запустить только stats_worker
```

Точка входа: `app/workers/__main__.py` — читает аргументы, создаёт event loop, запускает нужные корутины. Не импортирует FastAPI и не зависит от lifespan API-сервера.

В Docker Compose workers запускаются как отдельный сервис (`worker` container) с тем же образом, но разной командой: `command: python -m app.workers`.

**`alert_worker`** — запускается периодически (asyncio loop с sleep):
1. Вызывает `alert_service`.
2. `alert_service` → `chat_service` → считает red/unanswered чаты по проекту.
3. Если условие выполнено и нет непрочитанного алерта того же типа → пишет в `alerts`.
4. Работает батчами по project_id.

**`stats_worker`** — запускается раз в сутки:
1. Вызывает `stats_service`.
2. Агрегирует данные за прошедший день.
3. Пишет в `daily_stats`.

**`red_chat_worker` — УДАЛЁН.** Логика red больше не требует периодической маркировки в БД.

---

## 4. Взаимодействие между модулями

```
HTTP Request
    │
    ▼
API Router (валидация, auth, project_id)
    │
    ▼
Service ──────────────────────────────────────────────┐
    │                                                  │
    │  может вызывать другой Service                   │
    │                                                  ▼
    │                                         AuditService
    │                                              │
    ▼                                              ▼
Repository                                  AuditRepository
    │                                              │
    ▼                                              ▼
PostgreSQL                                   PostgreSQL


── При поступлении нового сообщения ──────────────────

MessageService
    ├──► ChatService.update_timestamps()    # last_user_message_at / last_manager_reply_at
    │        └──► ChatRepository
    └──► MessageRepository.create()

── При смене менеджера ────────────────────────────────

AssignmentService
    ├──► LeadRepository.update(manager_id=...)
    └──► AuditService.log(action="manager_changed", ...)
             └──► AuditRepository.create()

── При запросе списка чатов ───────────────────────────

ChatService.list_chats(filters)
    ├──► ChatRepository.list(filters, order_by=[is_red_expr, unanswered, last_activity])
    └──► Вычисляет is_red через SQL-выражение (timestamp comparison)
         Возвращает ChatOut с полем is_red: bool

── Workers (независимый asyncio цикл) ─────────────────

AlertWorker (каждые N минут)
    └──► AlertService
             └──► ChatService.count_red(project_id)   # без HTTP, прямой вызов
             └──► AlertRepository.create()

StatsWorker (раз в сутки)
    └──► StatsService
             ├──► LeadRepository.aggregate_by_status(date)
             ├──► MetricsService.avg_response_time(date)
             └──► StatsRepository.upsert(daily_stats)
```

---

## 5. Синхронные vs асинхронные части

### Синхронно (в рамках HTTP-запроса)

- CRUD чатов, сообщений, лидов, тегов.
- Смена статуса лида.
- Назначение / смена менеджера (обновление `lead.manager_id`).
- Запись в `audit_log` — **в той же транзакции**, что и основное действие. Если audit упал — откатывается всё.
- Обновление `last_user_message_at` / `last_manager_reply_at` при записи сообщения.
- Вычисление `is_red` при возврате списка чатов.
- Health check.

### Асинхронно (отдельный процесс, не блокируют API)

- `alert_worker` и `stats_worker` — запускаются через `python -m app.workers` в отдельном контейнере. Не привязаны к FastAPI lifespan.
- Все обращения к Redis — неблокирующие, через async-клиент.

### Подготовлено к асинхронному расширению (не строится сейчас)

- Redis как очередь сообщений от Telegram-источника — структура готова, consumers не пишем.
- Kafka — явно в DO_NOT_BUILD_YET, архитектура не зависит от неё.

### Масштабирование при тысячах чатов

- `is_red` вычисляется SQL-выражением на стороне БД — нет выборки всех строк в память.
- Сортировка (red → unanswered → latest activity) реализуется через `ORDER BY` в одном запросе с использованием индексов по `last_user_message_at`, `unanswered`, `project_id`.
- Workers работают батчами (LIMIT + OFFSET по project_id) — нет запросов "выбрать всё".
- `chat_repository.list()` всегда принимает `limit` / `offset` — бесконечной выборки нет.
- Индексы обязательны: `external_chat_id`, `external_user_id`, `project_id`, `manager_id`, `status`, `created_at`, `last_user_message_at`.

---

## Ограничения из DO_NOT_BUILD_YET.md — учтены

| Ограничение | Как учтено |
|---|--------|
| **GPT / AI** | Ни один модуль не содержит AI-логики |
| **Конструктор ботов / сценарии** | Нет модуля автоматизации |
| **A/B, постбеки, ссылки** | Отсутствуют |
| **Сложная аналитика / когорты** | Только flat daily_stats |
| **Telegram-уведомления** | AlertService пишет только в таблицу alerts |
| **Kafka** | Не используется; Redis — placeholder |
| **Kubernetes** | Только Docker Compose |
| **Сложный фронт** | Проектируется только backend |
| **Всё, что не влияет на обработку чатов** | Все модули проверены по этому правилу |

---

## Frontend modularity rules

Backend rule: `router -> service -> repository -> model`.

Frontend rule: `page -> feature public API -> feature internals -> shared`.

- Router не импортирует Repository напрямую. HTTP-слой работает через Service.
- Новую бизнес-логику нельзя добавлять внутрь крупных React page-компонентов.
- Новые крупные домены добавляются как отдельные feature-модули в `frontend/src/features`.
- Feature-модуль экспортирует публичный контракт через `index.ts`, `api.ts`, `types.ts` и `hooks.ts`.
- Feature не импортирует внутренние файлы другого feature напрямую.
- Общие UI-компоненты, API-клиенты, утилиты и типы живут в `frontend/src/shared`.
