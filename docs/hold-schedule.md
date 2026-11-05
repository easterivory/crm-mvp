# HOLD: project calendar and technician guide

## Deployment: main CRM server only

Apply migration `20261103_0093` after `0092` before starting updated API/workers.
It only adds projects.hold_schedule (empty JSON, disabled) and
funnel_versions.hold_mode (manual). No lead data, queues, published graphs or
existing manual HOLD flags are rewritten. Take a verified database backup first.
Rebuild the main image: tzdata is now explicitly installed for IANA timezones.
The migration uses a five-second lock timeout; on contention, stop and retry in
a quieter window, not by dropping data. No gateway deployment changes are needed.

## Настройка техника

1. Настройки → Проект → «HOLD · расписание записи». Указать часовой пояс,
   время отсечки, дни выдачи и при необходимости нерабочие даты. Выбрать,
   записывать ли до отсечки на сегодня или всегда на следующий рабочий день.
   Включить расписание и нажать «Сохранить расписание HOLD» отдельно от
   общей кнопки сохранения проекта.
2. В конструкторе НУЖНОЙ версии воронки в панели HOLD выбрать
   «По расписанию проекта». Настройка применяется именно к этой версии,
   в том числе к ещё не записанным людям на ней. Остальные версии остаются
   ручными. Новые черновики этой же воронки наследуют автоматический режим;
   копия в новую воронку начинает с ручного режима.
3. Разместить существующий блок «Hold: сегодня/завтра» в месте записи,
   например после контактов, и соединить обе ветки. В автоматическом режиме
   «Завтра» означает ближайший рабочий день, а не обязательно следующий
   календарный. Для вопроса времени (ask_call_time или save_to=call_time_text)
   автоматический режим сам сохраняет дату и продолжает по соответствующей
   ветке без ожидания ответа. Час созвона он не выбирает.
4. В текстах сообщений использовать `{{hold_date_label}}` (09.11.2026),
   `{{hold_date}}` (2026-11-09), `{{hold_timezone}}`. Поддерживается и
   `{{custom.hold_date}}`. Жёстко написанное «завтра» не переписывается:
   заменить его на дату в нужной ветке. В карточке дата также попадает в
   call_time_text / preferred_call_time при назначении через HOLD.
5. Для защиты записанных людей от рекламы добавить существующее
   CRM-действие с тегом записи и выбрать этот тег в защищённых тегах
   соответствующего рекламного сценария. В обычных рассылках исключить
   этот тег из аудитории. Сам HOLD не добавляет тегов и не меняет рассылки,
   VIP, статусы, подачу покупателю или уже заведённые рекламные очереди.

## Пример «Вакансии»

- Europe/Moscow, отсечка 18:00 включительно, дни Пн–Сб.
- До отсечки: сегодня, если день рабочий.
- Понедельник 17:59 → понедельник; 18:00 → вторник.
- Пятница после 18:00 → суббота.
- Суббота после 18:00 и всё воскресенье → понедельник.
- В 00:00 начинается новый день: понедельник 00:00 → понедельник.
- Если понедельник добавлен в нерабочие даты → ближайший разрешённый день.

## Правила совместимости

Дата определяется при первом выполнении HOLD-условия или вопроса времени,
не при старте бота. Сохраняется в runtime текущего прохождения и в custom_fields
лида. Редактирование календаря, полночь и повторное прохождение HOLD внутри того
же запуска не передвигают назначение. Сброс runtime/новое прохождение позволяет
назначить новую дату по текущему календарю. Старое поле в карточке до следующей
записи остаётся историей последнего назначения.

Отключённое расписание означает возврат к ручному флагу версии для ещё
не записанных людей. Существующие назначения сохраняются. При первоначальном
выборе автоматического режима выключенное расписание отклоняется с понятной
ошибкой. Изменение настроек не запускает, не останавливает и не перемещает чаты
самостоятельно; оно применяется при следующем выполнении соответствующего шага.

Расчёт не использует опрос базы по таймеру, внешние API или ИИ. Блокировки чата
остаются прежними, запись календаря выполняется в той же транзакции, что и шаг.
Уже отправленные сообщения не редактируются. Это не отложенная отправка лида
покупателю и не резервирование вместимости временных слотов.

## Локальные проверки

```sh
.venv/bin/python -m pytest -q tests/test_hold_schedule.py
```

Browser controls: start frontend Vite on 127.0.0.1:5181, then run
`node frontend/tests/run-hold-schedule.mjs` with Playwright available (or provide
PLAYWRIGHT_MODULE / CHROMIUM_PATH). API is mocked; no live Telegram traffic.
The test exercises both 390px and 1440px layouts.

Real PostgreSQL migration execution still requires a staging check: local
Docker's engine was unavailable during development. The local migration test
checks the additive operations/defaults, not a real production lock or runtime.
Run the gated PostgreSQL test only against a disposable database:

```sh
CRM_TEST_POSTGRES_URL=postgresql+asyncpg://USER:PASSWORD@HOST/TEST_DATABASE .venv/bin/python -m pytest -q tests/test_hold_schedule.py
```

Local final run: 880 passed, 79 skipped, 7 subtests passed. Frontend build passed;
browser checks passed at 390px and 1440px. No real messages or lead submissions
were sent. The skipped PostgreSQL test and container build are not claimed as
verified.
