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

## Backend layering rules

- Router handles HTTP only: request parsing, dependency wiring, service call, and response shaping.
- Service contains business logic and orchestration.
- Repository contains database access.
- Model defines persistence structure.
- Schema defines request/response DTOs.
- Router must not import Repository directly.
- Router must not perform SQLAlchemy queries directly.
- Service may coordinate multiple repositories.
- Repository must not import Router or Service.
- Cross-domain interaction should go through Services, not Repositories.
- Quick check: `python scripts/check_backend_layers.py`.

## Production UI/Workflow Cleanup — 2026-05-19

### Navigation IA

Основная навигация CRM отражает рабочий порядок: `Чаты → Воронки → Рассылки → Боты → Лиды → Трекинг → Аналитика → Настройки`.
`Dashboard` сохранён как backward-compatible route `/dashboard`, но пользовательский вход в обзор идёт через `/analytics` и пункт `Аналитика`.
`Воронки` и `Рассылки` пока являются placeholder-страницами; visual funnel builder и рассылочный движок в этот шаг намеренно не входят.

### Tracking Canonical Creation Flow

Tracking links создаются только в разделе `Трекинг` через кнопку `Создать ссылку`.
`BotsPage` больше не содержит форму создания tracking links и служит только для управления Telegram-ботами, webhook и токенами.
Если пользователю нужно создать source/link, UI отправляет его в `Трекинг`.

### Chat Reset Semantics

Reset чата не удаляет Telegram user и не удаляет старые сообщения физически.
Текущий lifecycle хранится на `chats`: `reset_at`, `reset_count`, `current_cycle_started_at`.
При reset CRM скрывает чат из активных списков, очищает lead tags, переводит текущий lead в `lost`, сбрасывает manager/contact поля лида, очищает активный `tracking_link_id` и деактивирует `chat_bot_states`.
Из-за уникального ограничения `project_id + bot_id + external_chat_id` новый lifecycle безопасно реализован на той же строке `chat`: когда Telegram user пишет снова, webhook реактивирует reset-chat, берёт новый `/start` ref_code при наличии, записывает новый `tracking_link_id` или оставляет attribution пустой без ref_code, очищает bot state и запускает bot funnel заново.
Messages API показывает только сообщения текущего lifecycle, если `current_cycle_started_at` задан.

### Chat lifecycle and tracking attribution

Фактический Telegram lifecycle:

1. Telegram webhook приходит на `/api/v1/telegram/webhook/{bot_id}`; `project_id` берётся из `Bot`, не из payload.
2. `/start ref_code` разбирается только как Telegram start payload. Tracking lookup проверяет `ref_code`, `project_id` и совпадение `bot_id`.
3. Chat lookup всегда scoped by `project_id + bot_id + external_chat_id`; один и тот же Telegram user в разных ботах получает разные chat lifecycle.
4. Новый chat создаётся с `tracking_link_id` из валидного `/start`, либо без attribution.
5. Lead создаётся один-к-одному к chat со статусом `new`; tags живут в `lead_tags`, definitions в `tags` не удаляются при reset.
6. Reset переводит текущий lead в `lost`, очищает `lead_tags`, `tracking_link_id`, timestamps active cycle и bot state, но не удаляет `messages`, `leads` или Telegram user data.
7. Пока `reset_at` заполнен, chat не возвращается из активного `GET /api/v1/chats` и lead не виден в default active leads list.
8. Следующее сообщение этого Telegram chat в том же bot реактивирует ту же строку `chats`, выставляет `current_cycle_started_at=now`, обновляет attribution из нового `/start ref_code` или оставляет её пустой, сбрасывает lead в `new` и стартует bot funnel сначала.

Tracking metrics считаются по текущему активному lifecycle. Для chats используется `coalesce(chats.current_cycle_started_at, chats.created_at)`, для leads - `coalesce(chats.current_cycle_started_at, leads.created_at)`. Reset chats (`reset_at IS NOT NULL`) исключаются из starts/leads/submitted/funnel snapshots. `submitted_leads` включает только статусы `submitted`, `applied`, `qualified`; `lost`/`rejected` туда не попадают.

### Leads Workflow

Страница `/leads` использует существующий leads API с фильтрами `project_id`, `bot_ids`, `status`, `date_from`, `date_to`, `tag_ids`, `search`, `limit`, `offset`.
`Отправить` сейчас является production-заглушкой внешней CRM: endpoint переводит lead в `qualified` и пишет audit event `lead.submitted_stub`, без fake external API call.
`Удалить` не удаляет физически: endpoint переводит lead в `lost` / rejected-archive semantics, после чего карточка уходит из активного списка.
Default `GET /api/v1/leads` без явного `status` показывает active view и исключает `lost`/`rejected`; явный `status=lost` или будущий `status=rejected` можно запросить отдельно.
Date filters on leads use the active lifecycle date (`current_cycle_started_at` after reset, otherwise `leads.created_at`), so a reactivated old lead appears in the current active window.

Manual smoke checklist:

- Reset chat in UI; confirm it disappears from active chat list and selected chat/lead sidebar are cleared.
- `GET /api/v1/chats?project_id=...` should not include the reset chat.
- `GET /api/v1/leads?project_id=...` should not include `lost`/`rejected` leads by default; explicit `status=lost` can return archived leads.
- Send `/start NEW_REF` to the same Telegram bot; confirm the chat reappears with the same `bot_id`, empty old tags, lead status `new`, and tracking identity for `NEW_REF`.
- Send a message after reset without `/start ref_code`; confirm the chat reappears without reusing the old tracking link.
- Repeat with the same Telegram user in another bot; reset in one bot must not affect the other bot's chat.

### Role Permission Matrix

Backend остаётся источником прав:
- `super_admin`: видит все проекты, управляет проектами и пользователями, может менять роли и пароли staff users.
- `admin`: управляет manager/operator только в своём project scope, не назначает admin/super_admin и не редактирует admin/super_admin.
- `manager` / `operator`: работают с чатами и лидами, не управляют проектами, командой, ролями и системными настройками.
- `buyer`: CRM UI не имеет; будущий buyer workflow должен идти через Telegram-бота.

User management использует soft delete (`is_deleted=true`). Новый password endpoint: `POST /api/v1/users/{user_id}/change-password`.

### Responsive Layout Rules

Desktop использует обычный collapsible sidebar. Tablet/mobile используют drawer/offcanvas с overlay.
Header selectors должны переноситься без horizontal body overflow. Таблицы остаются внутри локальных `overflow-x-auto` контейнеров.
Новые страницы обязаны поддерживать mobile one-column layout; чаты на mobile работают как список → экран диалога → drawer/modal карточки лида.

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

### Projects domain

`Project` — верхний scope CRM для будущих крупных доменов: Bots, Tracking
Links, Chats, Funnels и Analytics. Проект имеет стабильный `slug`, статус
`active` / `archived`, описание и timestamps.

Удаление проекта реализуется как archive: физическое удаление не используется.
Текущие связи существующих доменов не меняются в этом шаге. В актуальной
кодовой базе `Bot` уже содержит `project_id`; этот шаг не добавляет и не
переписывает эту связь.

### Bot project scope

Каждый `Bot` принадлежит одному `Project` через `bots.project_id`. Создание
бота проверяет, что проект существует и не архивирован. Существующие endpoints
сохраняют backward compatibility: `GET /bots` без query-параметра использует
проект текущего пользователя, а `GET /bots?project_id=<id>` возвращает ботов
выбранного проекта.

Новые scoped API должны принимать `project_id` там, где пользователь явно
выбирает проект. Позже frontend будет использовать общий `ProjectSelector` и
`BotSelector`.

### Project/Bot/User scope rules

- `ProjectSelector` в общем header является единственным глобальным выбором проекта.
- `BotSelector` в общем header является единственным глобальным выбором ботов.
- `selectedBotIds = []` означает all bots in selected project.
- Локальные bot selectors на страницах запрещены, если это не дополнительный фильтр,
  явно синхронизированный с global scope.
- `super_admin` имеет global access, не обязан иметь `project_id` и может видеть все проекты.
- `admin` работает в project-scoped режиме: управляет staff только внутри доступного проекта.
- `manager` и `operator` не управляют сотрудниками и проектами.
- Новые frontend-экраны читают project/bot scope через `useProjectBotSelection`.
- Backend остаётся источником прав доступа; frontend только скрывает недоступные действия.

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

## Tracking backend v1

- Tracking link принадлежит одновременно `project` и конкретному `bot`; `bot_id`
  должен относиться к тому же `project_id`.
- Старые поля `name/ref_code` сохранены для текущего `/tracking-links` API и
  Telegram `/start` attribution. Новые поля `title/code` являются v1-каноном и
  синхронизируются сервисом с legacy-полями.
- `code` глобально уникален, как и старый `ref_code`, чтобы inbound lookup из
  Telegram webhook оставался простым и не требовал угадывать project.
- Spend вводится вручную в CRM через `tracking_spends` с `source=crm_manual`.
- `source=buyer_bot` зарезервирован для будущей интеграции Telegram-бота баеров.
- Tracking metrics service будет отдельным следующим шагом; текущий v1 API
  подготавливает CRUD ссылок и ручной spend без графиков и dashboard-метрик.
- Permissions: `super_admin` видит и меняет tracking всех проектов; `admin`,
  `manager` и `operator` работают только внутри своего доступного project.
- Router вызывает только `TrackingService`; permission logic, проверка project,
  проверка bot->project и code generation живут в service layer.

## Tracking Metrics Service

- `clicks`: сумма `tracking_events.clicks` по `tracking_link_id` и дате
  `tracking_events.created_at`. Если events не пишутся, clicks остаются `0` и
  не подменяются starts.
- `starts`: количество уникальных active `chats`, где заполнен
  `tracking_link_id`; reset rows (`reset_at IS NOT NULL`) исключаются. Дата
  берётся из `coalesce(chats.current_cycle_started_at, chats.created_at)`,
  чтобы reactivation после reset попадала в период нового lifecycle.
- `leads`: количество `leads`, связанных через `Lead -> Chat -> tracking_link_id`;
  reset rows исключаются. Дата берётся из
  `coalesce(chats.current_cycle_started_at, leads.created_at)`.
- `submitted_leads`: текущие лиды со статусами `submitted`, `applied` или
  `qualified`. `lost` и `rejected` не считаются submitted. Явного
  `submitted_at` или истории статусов пока нет, поэтому период фильтруется по
  текущему lifecycle date, как у `leads`.
- `deposits`: возвращаются `0`, потому что deposit-сущности или deposit-поля
  в текущей схеме нет.
- `spend`: сумма `tracking_spends.amount` по `tracking_spends.spend_date`.
- `age_breakdown` и `country_breakdown`: возвращаются пустыми массивами, потому
  что возраст и гражданство не хранятся в `chats`/`leads`.
- `funnel_steps`: текущий snapshot `chat_bot_states.current_step_id` для чатов
  ссылки. Это не историческая воронка прохождения шагов.
- Division by zero policy: все rates и costs возвращают `0.00`, если
  denominator равен нулю.
- Default date range: последние 7 дней, `date_to=today`, `date_from=today-6`.
- Permissions: `super_admin` может читать метрики любого project; остальные
  роли читают только свой `project_id`. `bot_id` и `link_id` дополнительно
  проверяются на принадлежность доступному project.
