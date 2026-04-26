# Database Design — CRM MVP

> Основан на: ARCHITECTURE.md, PROJECT_SCOPE.md, TECH_REQUIREMENTS.md
> Версия: 2026-04-22 rev.2 (lead_statuses, phone/username, external_message_id, entity_type)

---

## Общие правила

- Все `id` — UUID, генерируются на стороне БД (`gen_random_uuid()`)
- Все временные метки — `TIMESTAMPTZ`, хранятся в UTC
- Soft delete — через `is_deleted BOOLEAN DEFAULT false` (критичные данные не удаляются)
- `is_red` и `unanswered` — **не хранятся**, вычисляются на лету (см. секцию «Вычисляемые поля»)
- `project_id` присутствует во всех ключевых таблицах
- Пагинация: все list-запросы используют `LIMIT` / `OFFSET`

---

## Перечень таблиц

| Таблица | Назначение |
|---|---|
| `projects` | Проекты — верхний уровень мультитенантности |
| `roles` | Справочник ролей пользователей |
| `lead_statuses` | Справочник статусов лида — изменяемый, без миграций |
| `users` | Пользователи системы |
| `chats` | Telegram-диалоги |
| `messages` | Сообщения внутри чата |
| `leads` | Бизнес-сущность, привязанная к чату |
| `tags` | Теги, принадлежащие проекту |
| `lead_tags` | Связь many-to-many: лид ↔ теги |
| `audit_logs` | Лог всех действий над сущностями |
| `alerts` | Записи о сработавших алертах |
| `daily_stats` | Агрегированная статистика за день |

---

## Таблицы: поля, типы, связи

---

### `projects`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `name` | VARCHAR(255) | NOT NULL | Название проекта |
| `sla_threshold_minutes` | INTEGER | NOT NULL, DEFAULT 30 | SLA-порог для красных чатов, per-project |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `is_deleted` | BOOLEAN | NOT NULL, DEFAULT false | Soft delete |

**FK входящие:** users, chats, leads, tags, audit_logs, alerts, daily_stats

---

### `roles`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `name` | VARCHAR(50) | NOT NULL, UNIQUE | super_admin / admin / manager |

**Примечание:** таблица статическая, заполняется при миграции (seed). Не редактируется через API.

---

### `lead_statuses`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `code` | VARCHAR(50) | NOT NULL, UNIQUE | Машинный код: new, in_progress, qualified, lost |
| `name` | VARCHAR(100) | NOT NULL | Человекочитаемое название |
| `sort_order` | INTEGER | NOT NULL, DEFAULT 0 | Порядок отображения |
| `is_final` | BOOLEAN | NOT NULL, DEFAULT false | Терминальный статус (qualified / lost) |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Почему не ENUM:** PostgreSQL ENUM требует `ALTER TYPE` для добавления значений — это блокирующая операция. Справочная таблица позволяет добавлять статусы в рантайме через INSERT без миграции схемы.

**Начальные строки (seed):**

| code | name | sort_order | is_final |
|---|---|---|---|
| `new` | Новый | 1 | false |
| `in_progress` | В работе | 2 | false |
| `qualified` | Квалифицирован | 3 | true |
| `lost` | Потерян | 4 | true |

**FK входящие:** `leads.status_id`

---

### `users`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NULLABLE, FK → projects(id) | NULL для super_admin |
| `role_id` | UUID | NOT NULL, FK → roles(id) | |
| `email` | VARCHAR(255) | NOT NULL, UNIQUE | |
| `name` | VARCHAR(255) | NOT NULL | |
| `password_hash` | TEXT | NOT NULL | |
| `is_deleted` | BOOLEAN | NOT NULL, DEFAULT false | Soft delete |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**FK:** `project_id → projects(id)`, `role_id → roles(id)`

---

### `chats`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NOT NULL, FK → projects(id) | |
| `external_chat_id` | VARCHAR(255) | NOT NULL | Telegram chat id |
| `external_user_id` | VARCHAR(255) | NOT NULL | Telegram user id |
| `contact_name` | VARCHAR(255) | NULLABLE | Имя контакта из Telegram (first_name + last_name) |
| `last_message_at` | TIMESTAMPTZ | NULLABLE | Обновляется при любом сообщении |
| `last_user_message_at` | TIMESTAMPTZ | NULLABLE | Обновляется при sender_type = 'user' |
| `last_manager_reply_at` | TIMESTAMPTZ | NULLABLE | Обновляется при sender_type = 'manager' |
| `last_read_at` | TIMESTAMPTZ | NULLABLE | Когда менеджер последний раз открыл чат |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Обновляется при любом изменении строки |
| `is_deleted` | BOOLEAN | NOT NULL, DEFAULT false | Soft delete |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**FK:** `project_id → projects(id)`

**Уникальность:** `UNIQUE(project_id, external_chat_id)` — один Telegram-чат уникален в рамках проекта

**Вычисляемые поля (не хранятся — см. отдельную секцию):**
- `unread` — выводится из `last_message_at` и `last_read_at`
- `unanswered` — выводится из `last_user_message_at` и `last_manager_reply_at`
- `is_red` — выводится из `unanswered` и разницы `now() - last_user_message_at`

---

### `messages`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `chat_id` | UUID | NOT NULL, FK → chats(id) | |
| `external_message_id` | VARCHAR(255) | NULLABLE | ID сообщения в Telegram (для дедупликации) |
| `message_type` | VARCHAR(30) | NOT NULL, DEFAULT 'text' | text / image / video / audio / file / sticker / system |
| `sender_type` | VARCHAR(20) | NOT NULL | 'user' / 'manager' / 'system' |
| `sender_id` | UUID | NULLABLE, FK → users(id) | NULL если sender_type = 'user' (внешний) |
| `body` | TEXT | NULLABLE | Текст сообщения. NULL для медиа без подписи |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**`sender_type`** — VARCHAR(20) с проверкой на уровне приложения. Допустимые значения: `user`, `manager`, `system`. Не ENUM.

**`message_type`** — тип сообщения. Допустимые значения: `text`, `image`, `video`, `audio`, `file`, `sticker`, `system`. Не ENUM. Позволяет принимать медиа-сообщения из Telegram без изменения схемы.

**`body`** — NULLABLE. Для медиа-сообщений без текстовой подписи (`message_type != 'text'`) может быть NULL.

**`external_message_id`** — Telegram message id. Используется для идемпотентной записи при ретраях. Уникальность — partial index: только когда значение не NULL, чтобы несколько system-сообщений без external_message_id не конфликтовали.

**FK:** `chat_id → chats(id)`, `sender_id → users(id)`

---

### `leads`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NOT NULL, FK → projects(id) | |
| `chat_id` | UUID | NOT NULL, UNIQUE, FK → chats(id) | 1 lead = 1 chat |
| `manager_id` | UUID | NULLABLE, FK → users(id) | Текущий менеджер (упрощённый assignment) |
| `status_id` | UUID | NOT NULL, FK → lead_statuses(id) | Ссылка на справочник статусов |
| `phone` | VARCHAR(50) | NULLABLE | Телефон лида |
| `username` | VARCHAR(255) | NULLABLE | Username лида (Telegram или иной) |
| `is_deleted` | BOOLEAN | NOT NULL, DEFAULT false | Soft delete |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Обновляется при любом изменении строки |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**FK:** `project_id → projects(id)`, `chat_id → chats(id)`, `manager_id → users(id)`, `status_id → lead_statuses(id)`

**Примечание по `status_id`:** при создании лида `status_id` ссылается на строку с `code = 'new'`. Смена статуса — это UPDATE `status_id` + запись в `audit_logs`. Добавить новый статус = INSERT в `lead_statuses`, без миграции.

**Примечание по assignment:** история смены менеджера хранится в `audit_logs`, не в отдельной таблице. Текущий менеджер — только `manager_id` здесь.

---

### `tags`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NOT NULL, FK → projects(id) | |
| `name` | VARCHAR(100) | NOT NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Уникальность:** `UNIQUE(project_id, name)` — имя тега уникально в рамках проекта

**FK:** `project_id → projects(id)`

---

### `lead_tags`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `lead_id` | UUID | NOT NULL, FK → leads(id) | |
| `tag_id` | UUID | NOT NULL, FK → tags(id) | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**PK:** `(lead_id, tag_id)` — составной первичный ключ

**FK:** `lead_id → leads(id)`, `tag_id → tags(id)`

---

### `audit_logs`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NOT NULL, FK → projects(id) | |
| `actor_id` | UUID | NULLABLE, FK → users(id) | NULL для системных действий |
| `action` | VARCHAR(100) | NOT NULL | Код действия: lead.status_changed, lead.manager_assigned, … |
| `entity_type` | VARCHAR(50) | NOT NULL | 'lead' / 'chat' / 'message' |
| `entity_id` | UUID | NOT NULL | ID сущности, над которой совершено действие |
| `meta` | JSONB | NULLABLE | Контекст: old_value, new_value, и др. |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**FK:** `project_id → projects(id)`, `actor_id → users(id)`

**Обязательные поля для поиска по истории:** `entity_type` + `entity_id` — составной индекс. Без них невозможно достать историю конкретного лида или чата. `entity_type` — строка: `'lead'`, `'chat'`, `'message'`. Не ENUM.

**Примеры `action`:** `lead.status_changed`, `lead.manager_assigned`, `lead.manager_removed`, `lead.created`

**Примеры `meta`:**
```
{ "old_status": "new", "new_status": "in_progress" }
{ "old_manager_id": null, "new_manager_id": "uuid-..." }
```

---

### `alerts`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NOT NULL, FK → projects(id) | |
| `type` | VARCHAR(100) | NOT NULL | 'long_response' / 'many_unanswered' |
| `payload` | JSONB | NULLABLE | Контекст: количество чатов, порог и др. |
| `is_read` | BOOLEAN | NOT NULL, DEFAULT false | Прочитан ли алерт |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**FK:** `project_id → projects(id)`

**Примеры `payload`:**
```
{ "unanswered_count": 47, "threshold": 20 }
{ "red_chat_count": 12, "sla_minutes": 30 }
```

---

### `daily_stats`

| Поле | Тип | Ограничения | Описание |
|---|---|---|---|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `project_id` | UUID | NOT NULL, FK → projects(id) | |
| `date` | DATE | NOT NULL | Дата за которую считается статистика |
| `new_chats` | INTEGER | NOT NULL, DEFAULT 0 | Новые чаты за день |
| `processed_chats` | INTEGER | NOT NULL, DEFAULT 0 | Переведены в in_progress |
| `qualified_chats` | INTEGER | NOT NULL, DEFAULT 0 | Переведены в qualified |
| `lost_chats` | INTEGER | NOT NULL, DEFAULT 0 | Переведены в lost |
| `avg_response_time_sec` | INTEGER | NULLABLE | Среднее время ответа в секундах |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Уникальность:** `UNIQUE(project_id, date)` — одна запись на проект за каждый день

**FK:** `project_id → projects(id)`

---

## Вычисляемые поля

Все три поля **не хранятся в БД** и не требуют воркера для обновления. Вычисляются SQL-выражением при каждом запросе списка чатов.

### `unread`

```
unread =
  last_message_at IS NOT NULL
  AND (
    last_read_at IS NULL
    OR last_message_at > last_read_at
  )
```

Смысл: в чате есть сообщение, которое менеджер ещё не читал. `last_read_at` обновляется явным API-вызовом когда менеджер открывает чат.

### `unanswered`

```
unanswered =
  last_user_message_at IS NOT NULL
  AND (
    last_manager_reply_at IS NULL
    OR last_user_message_at > last_manager_reply_at
  )
```

Смысл: последнее сообщение от пользователя — и менеджер после него не ответил.

### `is_red`

```
is_red =
  unanswered
  AND (now() - last_user_message_at) > INTERVAL '<SLA_THRESHOLD> minutes'
```

Смысл: чат без ответа дольше допустимого времени. `SLA_THRESHOLD` берётся из `core/config.py`.

### Применение при сортировке

Сортировка чатов (red → unanswered → latest activity) реализуется одним SQL ORDER BY:

```
ORDER BY
  is_red_expr DESC,       -- вычисляемое выражение
  unanswered_expr DESC,   -- вычисляемое выражение
  last_message_at DESC    -- хранимое поле
```

Производительность обеспечивается индексами на `last_user_message_at`, `last_manager_reply_at`, `last_message_at`, `project_id`.

---

## Индексы

### `projects`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |

### `roles`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |
| UQ | `name` | UNIQUE |

### `users`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |
| UQ | `email` | UNIQUE |
| IDX | `project_id` | BTREE |
| IDX | `role_id` | BTREE |

### `chats`
| Индекс | Поля | Тип | Обоснование |
|---|---|---|---|
| PK | `id` | PRIMARY | |
| UQ | `(project_id, external_chat_id)` | UNIQUE | Уникальность чата в проекте |
| IDX | `project_id` | BTREE | Все list-запросы фильтруют по проекту |
| IDX | `external_chat_id` | BTREE | Поиск по Telegram id |
| IDX | `external_user_id` | BTREE | Поиск по Telegram user |
| IDX | `last_user_message_at` | BTREE | Вычисление unanswered / is_red |
| IDX | `last_manager_reply_at` | BTREE | Вычисление unanswered / is_red |
| IDX | `last_message_at` | BTREE | Сортировка по активности; вычисление unread |
| IDX | `last_read_at` | BTREE | Вычисление unread |
| IDX | `updated_at` | BTREE | Инкрементальная синхронизация |
| IDX | `created_at` | BTREE | Фильтрация по дате |
| IDX (composite) | `(project_id, last_user_message_at)` | BTREE | Основной запрос списка чатов |
| IDX (composite) | `(project_id, last_message_at)` | BTREE | Сортировка в рамках проекта |

### `lead_statuses`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |
| UQ | `code` | UNIQUE |

### `messages`
| Индекс | Поля | Тип | Обоснование |
|---|---|---|---|
| PK | `id` | PRIMARY | |
| PARTIAL UQ | `(chat_id, external_message_id) WHERE external_message_id IS NOT NULL` | UNIQUE | Дедупликация: только для сообщений с Telegram id; system-сообщения без id не конфликтуют |
| IDX | `chat_id` | BTREE | Все сообщения чата |
| IDX | `external_message_id` | BTREE | Поиск по Telegram message id |
| IDX | `sender_type` | BTREE | Фильтрация по типу отправителя |
| IDX | `created_at` | BTREE | Хронологический порядок |
| IDX (composite) | `(chat_id, sender_type, created_at)` | BTREE | SLA-запросы: первый ответ менеджера |

### `leads`
| Индекс | Поля | Тип | Обоснование |
|---|---|---|---|
| PK | `id` | PRIMARY | |
| UQ | `chat_id` | UNIQUE | 1 lead = 1 chat |
| IDX | `project_id` | BTREE | Все лиды проекта |
| IDX | `manager_id` | BTREE | Лиды менеджера |
| IDX | `status_id` | BTREE | Фильтрация по статусу |
| IDX | `updated_at` | BTREE | Инкрементальная синхронизация |
| IDX | `created_at` | BTREE | Сортировка |
| IDX (composite) | `(project_id, status_id)` | BTREE | Агрегация для daily_stats |
| IDX (composite) | `(project_id, manager_id)` | BTREE | Нагрузка менеджера |

### `lead_tags`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `(lead_id, tag_id)` | PRIMARY (также индексирует lead_id) |
| IDX | `tag_id` | BTREE |

### `tags`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |
| UQ | `(project_id, name)` | UNIQUE |
| IDX | `project_id` | BTREE |

### `audit_logs`
| Индекс | Поля | Тип | Обоснование |
|---|---|---|---|
| PK | `id` | PRIMARY | |
| IDX | `project_id` | BTREE | Лог в рамках проекта |
| IDX | `actor_id` | BTREE | Действия конкретного пользователя |
| IDX (composite) | `(entity_type, entity_id)` | BTREE | История конкретной сущности |
| IDX | `created_at` | BTREE | Хронологический порядок |

### `alerts`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |
| IDX | `project_id` | BTREE |
| IDX | `is_read` | BTREE |
| IDX | `created_at` | BTREE |

### `daily_stats`
| Индекс | Поля | Тип |
|---|---|---|
| PK | `id` | PRIMARY |
| UQ | `(project_id, date)` | UNIQUE (также служит индексом) |

---

## Текстовая ER-диаграмма

```
┌──────────────────┐    ┌────────────────────┐
│     projects     │    │       roles         │
│──────────────────│    │────────────────────│
│ id (PK)               │◄─┐ │ id (PK)            │◄──┐
│ name                  │  │ │ name UNIQUE         │   │
│ sla_threshold_minutes │  │ │  super_admin        │   │
│ created_at            │  │ │  admin              │   │
│ is_deleted            │  │ │  manager            │   │
└────────┬──────────────┘  │ └────────────────────┘   │
         │ 1          │ └────────────────────┘   │
    ┌────┴─────┐       │                          │
    │          │       │  ┌──────────────────────┐│
    ▼ N        ▼ N     │  │    lead_statuses      ││
┌──────────┐  ┌───────────────────────────────────────┐
│  users   │  │               chats                   │
│──────────│  │───────────────────────────────────────│
│ id (PK)  │  │ id (PK)                               │
│project_id│  │ project_id (FK → projects)            │
│role_id──────►│ external_chat_id  ← UNIQUE per proj  │
│email     │  │ external_user_id  ← indexed           │
│name      │  │ contact_name      ← NULLABLE          │
│password_ │  │ last_message_at   ← хранимое         │
│  hash    │  │ last_user_message_at  ← хранимое     │
│is_deleted│  │ last_manager_reply_at ← хранимое     │
│created_at│  │ last_read_at      ← хранимое         │
└────┬─────┘  │ [unread]      ← COMPUTED, не хранится│
     │        │ [unanswered]  ← COMPUTED, не хранится│
     │        │ [is_red]      ← COMPUTED, не хранится│
     │        │ updated_at, is_deleted, created_at   │
     │        └───────────────┬───────────────────────┘
     │                        │ 1
     │                        ▼ N
     │              ┌──────────────────────────────┐
     │              │          messages             │
     │              │──────────────────────────────│
     │              │ id (PK)                      │
     │              │ chat_id      (FK → chats)    │
     │    ┌─────────│ sender_id    (FK → users) ?  │
     │    │         │ external_message_id NULLABLE  │
     │    │         │   PARTIAL UNIQUE WHERE NOT NULL│
     │    │         │ message_type VARCHAR(30)      │
     │    │         │   text/image/video/…/system  │
     │    │         │ sender_type  VARCHAR(20)      │
     │    │         │   user / manager / system    │
     │    │         │ body TEXT  NULLABLE           │
     │    │         │ created_at                   │
     │    │         └──────────────────────────────┘
     │    │
     │    │         ┌────────────────────────────────────────┐
     │    │         │                leads                   │
     │    │         │────────────────────────────────────────│
     │    └────────►│ id (PK)                                │
     │              │ project_id  (FK → projects) ───────────►projects
     │              │ chat_id     (FK → chats)  ← UNIQUE     │
     └─────────────►│ manager_id  (FK → users)  ← NULLABLE   │
                    │ status_id   (FK → lead_statuses) ──────►lead_statuses
                    │ phone       VARCHAR(50)   NULLABLE      │
                    │ username    VARCHAR(255)  NULLABLE      │
                    │ updated_at, is_deleted, created_at      │
                    └──────────────┬─────────────────────────┘
                                   │ 1
                                   ▼ N
                    ┌──────────────────────┐
                    │      lead_tags       │
                    │──────────────────────│
                    │ lead_id (FK→leads) PK│
                    │ tag_id  (FK→tags)  PK│
                    │ created_at           │
                    └──────────┬───────────┘
                               │ N
                               ▼ 1
                    ┌──────────────────────┐
                    │        tags          │
                    │──────────────────────│
                    │ id (PK)              │
                    │ project_id (FK) ─────►projects
                    │ name                 │
                    │ created_at           │
                    └──────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                       lead_statuses                            │
│────────────────────────────────────────────────────────────────│
│ id (PK)                                                        │
│ code       VARCHAR(50)  UNIQUE  — new / in_progress / …        │
│ name       VARCHAR(100)         — человекочитаемое             │
│ sort_order INTEGER                                             │
│ is_final   BOOLEAN              — qualified / lost = true      │
│ created_at                                                     │
└────────────────────────────────────────────────────────────────┘
  ▲ FK: leads.status_id → lead_statuses.id

┌─────────────────────────────────────────────────────────────┐
│                      audit_logs                             │
│─────────────────────────────────────────────────────────────│
│ id (PK)                                                     │
│ project_id  (FK → projects)                                 │
│ actor_id    (FK → users, NULLABLE)                          │
│ action      VARCHAR(100)  — lead.status_changed, …          │
│ entity_type VARCHAR(50)   — 'lead' / 'chat' / 'message'  ← │
│ entity_id   UUID          — id сущности                     │
│ meta        JSONB         — {old_value, new_value, …}       │
│ created_at                                                  │
│                                                             │
│  INDEX: (entity_type, entity_id) — история сущности         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                        alerts                               │
│─────────────────────────────────────────────────────────────│
│ id (PK)                                                     │
│ project_id  (FK → projects)                                 │
│ type        — 'long_response' / 'many_unanswered'           │
│ payload     JSONB  — {count, threshold, …}                  │
│ is_read     BOOLEAN                                         │
│ created_at                                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      daily_stats                            │
│─────────────────────────────────────────────────────────────│
│ id (PK)                                                     │
│ project_id          (FK → projects)                         │
│ date                DATE        UNIQUE(project_id, date)    │
│ new_chats           INTEGER                                 │
│ processed_chats     INTEGER                                 │
│ qualified_chats     INTEGER                                 │
│ lost_chats          INTEGER                                 │
│ avg_response_time_sec  INTEGER  NULLABLE                    │
│ created_at                                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Сводная таблица связей (FK)

| Таблица | Поле | Ссылается на |
|---|---|---|
| `users` | `project_id` | `projects(id)` — NULLABLE |
| `users` | `role_id` | `roles(id)` |
| `chats` | `project_id` | `projects(id)` |
| `messages` | `chat_id` | `chats(id)` |
| `messages` | `sender_id` | `users(id)` — NULLABLE |
| `leads` | `project_id` | `projects(id)` |
| `leads` | `chat_id` | `chats(id)` — UNIQUE |
| `leads` | `manager_id` | `users(id)` — NULLABLE |
| `leads` | `status_id` | `lead_statuses(id)` |
| `tags` | `project_id` | `projects(id)` |
| `lead_tags` | `lead_id` | `leads(id)` |
| `lead_tags` | `tag_id` | `tags(id)` |
| `audit_logs` | `project_id` | `projects(id)` |
| `audit_logs` | `actor_id` | `users(id)` — NULLABLE |
| `alerts` | `project_id` | `projects(id)` |
| `daily_stats` | `project_id` | `projects(id)` |

---

## Примечания по масштабированию

`chats` — самая нагруженная таблица. При тысячах чатов:

- Запрос списка чатов (с фильтрами и сортировкой) опирается на составной индекс `(project_id, last_user_message_at)` и `(project_id, last_message_at)` — полного скана таблицы нет.
- `unanswered` и `is_red` вычисляются как SQL CASE/WHERE выражения над индексированными полями — строки не тащатся в Python.
- `messages` растёт быстрее всего. Индекс `(chat_id, sender_type, created_at)` покрывает SLA-запросы без дополнительных JOIN.
- `audit_logs` — только INSERT. Индекс `(entity_type, entity_id)` позволяет быстро достать историю конкретной сущности.
- Партиционирование таблиц пока не требуется (MVP). Закладывать архитектуру с `created_at` в индексах достаточно для будущего партиционирования по дате.
