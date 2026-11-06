# Chatterfy Import: Read-Only Verification First

## Подготовка импорта в Сферу (6 ноября 2026)

Это подготовка, НЕ разрешение запускать импорт на рабочей базе. Проверен только
`@Andrey_smirniy_nobot`; остальные боты не выгружаются. Токен Telegram не получен,
webhook не менялся, рабочая база не менялась. Миграции и новые зависимости не нужны.

### Что реализовано

- `scripts/chatterfy_prepare.py`: офлайн-проверка существующих полных выгрузок
  отдельных чатов, отчёт по источникам/тегам/текущим шагам и шаблон сопоставления.
  Отчёт явно НЕ утверждает, что выгружена вся база. Ограничение одной партии:
  128 MiB входных JSON, 2000 чатов, 100000 исходных сообщений. Большую выгрузку
  разбивать на партии; не грузить 41000 диалогов в память рабочего API.
- `scripts/chatterfy_stage.py`: по умолчанию только проверка назначения в
  PostgreSQL-транзакции READ ONLY. Для записи нужны `--apply` и повтор точного
  UUID бота в `--confirm-bot-id`. Это технический инструмент, не страница импорта.
- Запись разрешена только в явно указанный бот-черновик без токена, Telegram ID,
  активной воронки и включённого для него рекламного сценария. Сам инструмент
  не создаёт бота, не подключает токен и не активирует доставку.
- В каждой партии сначала проверяются ВСЕ выбранные чаты. После проверки запись
  идёт с commit на чат. Ошибка после нескольких commit не отменяет предыдущие
  чаты; повтор неизменённого архива их пропускает. Другой архив того же чата,
  существующая живая/удалённая карточка, неоднозначная Telegram-личность — конфликт,
  а не разрешение перезаписать или «склеить» данные. Автоматической дельта-сверки
  и перезаписи изменившейся истории пока нет.
- Сохраняются исходные даты, Telegram ID, автор «лид/бот/оператор», связи ответов,
  отметка удаления и исходные идентификаторы. Оператор Chatterfy НЕ назначается
  пользователю Сферы по совпадению имени. Время удаления, если его нет в API,
  означает время наблюдения удаления при импорте, не выдуманную дату действия.
- Неотправленные (`failed`, `waiting`, `schedule`) сообщения остаются в архиве,
  но не создаются как доставленная переписка и не попадают в очередь отправки.
- Сообщения вставляются напрямую как история, без MessageService, рассылок,
  очереди, переводчика, отправки конверсий и выполнения CRM-действий воронки.
- Исходные message UUID НЕ выдаются за Telegram message ID. Поэтому Telegram-
  редактирование/удаление и настоящий Telegram-reply к старому сообщению не
  гарантируются. Внутренняя связь ответов истории сохраняется.
- В карточке диалога есть компактный блок источника Chatterfy: бот, ID кампании
  и ID источника. После явного сопоставления также работает обычная рекламная
  ссылка Сферы и её фильтр. Исходные данные сохраняются отдельно в
  `Lead.custom_fields.__chatterfy_import`.

### Вложения: обязательный незавершённый этап

Текущая запись в черновик поддерживает ТОЛЬКО текстовые чаты. Любой доставленный
файл блокирует запись ВСЕЙ выбранной партии до первого commit. Нет режима «молча
пропустить вложения». Получены метаданные фото/голоса/документа и проверены первые
байты нескольких файлов, но это не полное скачивание и не перенос вложений.
Перед массовым импортом нужен отдельный проверенный механизм: полная загрузка
из разрешённых HTTPS-хранилищ без API-ключа, ограничения размера/диска, проверка
типов, приватное хранение, несколько файлов/альбомы и просмотр из Сферы. Текущий
инструмент нельзя объявлять готовым полным импортом или обходить эту проверку.

### Трекинг и ссылки

Подтверждено на реальных чатах: `chat.lead` содержит `campaign_id`, `source_id`,
`params`, события; в истории есть `/start t_<код>`. Источник и все наблюдавшиеся
start-коды сохраняются раздельно. В одном чате могут быть последующие заходы по
другим ссылкам: последний start НЕ заменяет исходный источник автоматически.
Есть пример, где источник organic отличается от start-кодов. Не угадывать
источник по одному сообщению и не назначать все коды одной кампании одному баеру.

Ключ читает чаты и справочник тегов, но GET трёх кампаний из образцов вернул 403.
Нужен доступ **на чтение Tracker (`campaign.read`)** для названий, доменов,
баеров, источников и настроек кампаний. Права самостоятельно не повышать.
Полный справочник Смирнова: 260 тегов, получен тремя страницами; нельзя считать
первые 25 тегов всем справочником. Секреты пикселей/партнёров не копировать.

Рекомендуемое правило:

1. По подтверждённому источнику создать отдельную ссылку Сферы и явную таблицу
   `campaign_id + source_id -> tracking_link_id`. Шаблон содержит предложения
   с техническим названием до получения названий кампаний. Это не «воссозданные
   рекламные настройки» и не назначение баера по догадке.
2. Новым ссылкам по умолчанию предлагается новый уникальный код `chf_...`.
   `--create-links` с `--apply` создаёт только согласованные ссылки на боте-
   черновике; существующие коды и ссылки не меняет. Ссылки создаются inactive,
   но это НЕ защита от deep-link атрибуции: существующий обработчик `/start`
   разрешает код и для inactive-ссылки. Изоляция обеспечена отсутствием токена.
3. Если нужно сохранить прямую `t.me/тот_же_бот?start=t_...`, можно явно заменить
   предложенный `code` на наблюдавшийся `observed_legacy_payload`. Сфера уже
   разбирает такой payload. Проверить глобальную уникальность и принадлежность
   именно этому боту. Коллизия останавливает запись; не перезаписывать чужой код.
4. Ссылку на **домене Chatterfy** это не переносит. Для неё нужен отдельно
   согласованный редирект/управление доменом либо замена URL в рекламе. Исходный
   query-параметр `start` сам по себе не сохраняет лендинг, пиксель и click ID.
5. Старые клики, расходы, подписки, депозиты и серверные конверсии не
   синтезируются из количества чатов. События Tracker пока сохраняются как
   исходные данные, НЕ как подтверждённые постбэки/FD/RD Сферы.

**Влияние на статистику:** импорт ничего не отправляет в рекламные кабинеты,
но после записи исторические чаты и `/start` видны обычным SQL-отчётам Сферы с
исходными датами. В том числе это может изменить, какой старт считается первым
в проекте у человека, уже существующего в другом боте. Это правильное следствие
добавления истории, а не обещание «статистика совсем не изменится». Перед
рабочим импортом сверить отчёты на копии полной базы проекта. Импортированным
тегам нельзя выдавать текущую дату как фактическую дату прохождения этапа:
исходная история присвоения тегов пока не восстановлена. В staging-таблице
LeadTag.created_at означает дату импорта, а не событие прохождения воронки.

### Воронка и продолжение

Public API подтверждает текущий `current_step_id` в чате, но использованный
документированный API не даёт проверенного экспорта графа воронки. Доступ
`flow.read` в разрешениях бота сам по себе не доказывает наличие метода Public API.
Функция Import Flow в интерфейсе Chatterfy переносит сценарии между его ботами,
это НЕ совместимый импорт в Сферу.

Для переноса нужен отдельный экспорт структуры из интерфейса/поддержки либо
восстановление графа с проверкой каждого типа блока, перехода, переменной,
клавиатуры, задержки, AI и webhook. Создавать только черновик Сферы, не публиковать
автоматически и не переносить URL/секреты webhook как работающие интеграции.

По умолчанию вся импортированная база — **ручная**. Обычный ввод, повторный
`/start`, старый callback или подписка не должны запустить для неё текущую
воронку. Для входящего текста/callback и канальной подписки добавлены отдельные
проверки provenance; рекламный сценарий тоже не активируется автоматически.
Старые источники не создают работающие callback-кнопки Chatterfy в Сфере.

Дальнейшее безопасное продолжение потребует ОТДЕЛЬНОГО механизма и согласования:

- таблица `old_step_id -> published_version_id + new_step_id` с ручной проверкой;
- только живые чаты, которые действительно ждут ответ, а не manual/stopped/
  finished/blocked; отдельно исключить отказы/конечные состояния;
- восстановить переменные и ожидание ответа без выполнения входа на шаг,
  повторной отправки вопроса и внешних действий;
- не переносить старую очередь дожимов; таймеры после переноса — отдельное правило;
- для старых inline-кнопок не обещать совместимость; при необходимости однократно
  отправить новую клавиатуру только после согласования;
- сначала несколько согласованных тестовых чатов, затем небольшой пакет;
  непроверенные типы шагов оставлять на ручном ведении.

В этой версии автоматического продолжения и кнопки «включить продолжение» НЕТ.
Простое нажатие «Продолжить воронку» не отменяет ручную provenance-защиту.
Массовое снятие защиты без проверенной привязки шагов запрещено.

### Использование подготовки

```sh
.venv/bin/python scripts/chatterfy_prepare.py \
  --archive-dir /private/path/chatterfy-sample \
  --source-bot-id 019f2c6d-dc0e-72ee-8792-3cc410f797f4 \
  --source-username Andrey_smirniy_nobot \
  --tags-file /private/path/complete-tags.json \
  --output /private/path/new-preparation
```

`mapping-template.json` приватный (600). Заполнить destination UUID проекта,
бота-черновика и выбранного статуса для ручного импорта; сопоставить ВСЕ source-
теги и источники. Не подставлять случайный UUID вместо неизвестного назначения.
Свежий API-архив для финального переноса и сверка дельты пока обязательны:
пока бот работает в Chatterfy, состояние/история меняются.

```sh
# Проверка существующих назначений, без записи:
.venv/bin/python scripts/chatterfy_stage.py \
  --archive-dir /private/path/text-only-batch \
  --mapping /private/path/filled-mapping.json
```

Реальное выполнение требует отдельного согласования и бэкапа. Наличие ключа
Chatterfy или этого документа не является таким согласием. В подготовке на
6 ноября проверены 10 чатов / 365 записей, из них 356 готовы к сохранению как
история (355 ready + 1 removed), 9 неотправленных не подлежат воспроизведению.
Вложения в этих образцах намеренно блокируют фактическую запись.

## Agreed Scope

- Source: `@Andrey_smirniy_nobot`, bot ID
  `019f2c6d-dc0e-72ee-8792-3cc410f797f4`, Space
  `019f2c5c-1eaa-79be-be26-a8d0d08e5d68`. Exact username verified against the
  authenticated bot catalog on 6 November 2026; never select by name alone.
- Destination: the existing "Ru gambling" project. Destination bot has not been
  transferred or connected yet; do not create a replacement identity by name.
- Cohort: chats CREATED on or after 1 August 2026, 00:00 Europe/Moscow, including
  that boundary (`2026-07-31T21:00:00Z`), not old chats merely active after it.
- Export full available message history of selected chats, not just messages
  after the cohort boundary. Source completeness must be compared with its UI.
- No bot transfer, webhook change, CRM DB writes, lead messages or automations
  during the verification stage.

## Current State

The official documentation was read on 5 November 2026. It confirms inclusive
`created_at`/`between`, filtered stats, snapshot chat export with cursor expiry
after five minutes, and separately paginated messages. It does NOT prove access,
history completeness or media availability on this customer's account.

A key supplied through a private local file was used for a read-only verification
on 6 November 2026. The shipped tool is a bounded probe, NOT a production importer
or a full bulk export. Automated tests use mocked HTTP responses; the real source
checks below are separate. The key is never copied into this repository.

### Verified on the Source Account

- Exact username and source bot/Space identity, full-scope read/export access.
- Cohort count: 41,580 at the test cutoff. A separate strict-before query counted
  67,565 pre-August chats. The first Moscow day of August counted 151 chats
  (the tested interval includes both endpoints). Counts are snapshots, not an SLA.
- Ten selected chats, all within the requested cohort: 365 message records,
  including 355 ready, 9 failed and 1 removed. Do not treat the latter two as
  delivered messages or replay them into Telegram.
- 140 incoming / 225 outgoing messages, 107 with operator attribution,
  five reply references, and mailing flags were returned.
- A 159-record dialogue exhausted two 100-record pages. A second fetch of a
  34-record dialogue in five-record pages exhausted seven pages and returned
  the same IDs with no missing or additional records.
- Media metadata: 52 photos, one voice, one document. Bounded HTTPS Range reads
  of one file of each type returned 206 with content bytes. No API key was sent
  to media hosts. Full media downloads, complete media validation and future URL
  lifetime guarantees have NOT been established.
- No edited-message example was found; that case still needs source validation.
- UI-to-API history comparison and destination bot mapping are still pending.
- No CRM DB writes, bot transfer, webhook changes or message sends occurred.

Private raw data and reports are outside the repository in
`/Users/art/.codex/chatterfy-import/`. Do not include them in deployment artifacts.

## Access

Create a service account and add it to the bot's Space. A custom role with full
`bot.read`, `chat.read`, `chat.export`, `message.read`, `chat.contacts.read` is
preferable; built-in Space controller includes export but also write privileges.
Company Operator is sufficient for bot/chat work according to the documentation.
The tool permits only an explicit list of documented read/export API calls even
if the key has broader permissions. Scope must be `all`, not assigned/own chats.

Put the service key alone in a local private file (permissions 600). Do not put
it in source code, command arguments, a shared folder, Git, logs, or this chat.
Use a fresh private output directory outside shared folders. Export files contain
private conversations and possibly signed media URLs; do not commit/upload them.

Discover visible bots first:

```sh
.venv/bin/python scripts/chatterfy_probe.py \
  --api-key-file /private/path/chatterfy.key \
  --output /private/path/chatterfy-discovery
```

Confirm Smirnov's exact bot and Space in `bots.json` against the Chatterfy UI.
Do not select a bot based only on a display-name substring.

Then export a sample, not the whole cohort:

```sh
.venv/bin/python scripts/chatterfy_probe.py \
  --api-key-file /private/path/chatterfy.key \
  --bot-id SOURCE_BOT_ID \
  --expected-username Andrey_smirniy_nobot \
  --sample-size 5 \
  --output /private/path/chatterfy-sample
```

The script defaults to the agreed Moscow cutoff. It verifies full API scope,
counts the filtered cohort, selects up to five chats, then exhausts message pages
for each. Data is saved as private JSON files; the report records pagination,
message authors/statuses, media metadata, edits and replies. HTTP calls are
sequential and spaced by at least 0.6 seconds. Retries and total requests are
bounded. No redirects are followed with the service key.

No media are downloaded yet, and no report claims UI comparison or all-chat
completion. Page/request limits, cursor expiry, scope/schema mismatch and API
errors stop the run. Partial files are NOT a completed export. Start a new probe
in a new directory; existing files are never overwritten. HTTP 401/403 is not
retried. A long Retry-After stops rather than retrying prematurely.

## Gate Before Running the Production Import

1. Check exact bot identity and reported cohort size; compare the Moscow date
   boundary with a known source chat, including a pre-boundary exclusion.
2. Compare API/UI history in 5-10 chats, including one with more than 100 messages,
   one with photo/voice/document, and operator/mailing/reply/edited messages.
   Add targeted known source chat IDs if the default sample lacks these cases.
3. Determine media URL lifetimes and download/format rules. Do not promise deleted
   messages can be recovered or that every attachment URL will remain usable.
4. Inspect real sender/status fields. Scheduled/failed outgoing messages are not
   delivered history and must never be replayed in Telegram.
5. Confirm destination CRM bot mapping. Chatterfy message IDs are NOT assumed to
   be Telegram message IDs. Source ID deduplication must be separate.
6. Design and test an additive, resumable importer on an isolated database:
   exact project/bot/Telegram identity, collision report, unchanged existing
   manager assignments/status/tags/history, stable original timestamps, replies,
   edits and accessible attachments. Do not deduplicate by username alone.
7. Import historical messages without MessageService send/translation/tracking
   side effects, funnel starts, pushes, ads or new-start statistics. Specify how
   imported read/unanswered state appears before enabling it on the live project.
8. Verify repeat/resume makes no duplicates and reports incomplete chats; run
   one source-bot export inventory before histories to avoid cursor expiry.
9. Review counts/errors on a local trial, take a verified production backup,
   then explicitly approve execution with exact source/destination IDs.

Existing Google Sheets bot import creates contact cards only; it is not a
full-conversation importer and must not be presented as one. Neither this tool
nor preparing an archive requires switching Smirnov's Telegram bot webhook.

## Primary References

- https://docs.chatterfy.ai/en/public-api/guides/export-chats
- https://docs.chatterfy.ai/en/public-api/guides/read-chats
- https://docs.chatterfy.ai/en/public-api/guides/chat-filters
- https://docs.chatterfy.ai/en/public-api/getting-started/first-request
- https://docs.chatterfy.ai/en/public-api/getting-started/access-and-roles
- https://docs.chatterfy.ai/en/public-api/guides/analytics-and-tracker
- https://docs.chatterfy.ai/en/public-api/ai/connect-ai
