# Облачный помощник: локальная проверка 07.11.2026

Только локальные одноразовые PostgreSQL/Redis и тестовые данные. Production,
Telegram, OpenAI и кабинеты партнёров не вызывались. Включение модуля на сервере
этим документом не разрешается. Памятка настройки: `cloud-assistant-setup.md`.

Итог последнего общего прогона: **1160 passed, 5 skipped, 7 subtests passed**
(136.78 сек). Профильный модуль: **33 passed**. MCP contract, browser suites
и TypeScript/Vite build прошли. Ниже перечислены границы этих результатов.

## Проверенные риски

- OAuth code одноразовый, PKCE S256, точный callback/resource/issuer, public и
  confidential clients. Неверный verifier не расходует code. Refresh rotation,
  replay всей семьи, безопасные protocol errors, отзыв и смена resource.
- Существующий CRM JWT не принимается cloud API, opaque OAuth token не принимается
  native approve. Обязательны login, Origin и правильный hash. Чужой проект,
  лишние поля и несуществующие команды не проходят.
- До подтверждения нет новых офферов/endpoint. Пять параллельных approve создают
  одну сущность и один audit; потерянный prepare восстанавливается тем же request_id.
  Замена отменяет прежнюю заявку. Сбой второй операции откатывает первую.
- TTL, отзыв пользователя/проекта/scope/роли, изменение зависимости и истёкший
  secure input запрещают старое подтверждение. Секретная ссылка не попадает в diff.
- Офферы и standalone endpoints остаются выключенными. Приёмник с предыдущей
  активностью или неизвестной старой ревизией нельзя редактировать. Скрытая
  привязка финансовой политики сохраняется, не выводится в diff.
- Оффер назначается только черновику; опубликованная версия и текущий бот не
  меняются. Каталог/настройки/трекинг/диагностика и syntax preview проверены
  настоящими SQL-запросами, а не только моками бизнес-сервисов.
- Миграция 0098 исполнена на тестовой legacy-схеме: старые лиды/endpoint token и
  is_active сохраняются, legacy ever_active=true, таблицы помощника пустые.
- При выключенном флаге пул помощника не создаётся. При недоступном Redis limiter
  и heavy lease запрещают исполнение. Размеры и набор аргументов ограничены.
- Кэш отчётов имеет отдельный namespace/TTL 30 секунд и ограничение 64 KiB.
  Повтор запроса возвращает прежний generated_at; изменение policy даёт miss.
  Проверка доступа предшествует обращению к кэшу.
- Официальный MCP ClientSession выполнил initialize/list/call против ASGI-адаптера:
  discovery, 401, лимит тела, отсутствие apply и запрет лишних SQL-аргументов.
- Playwright 390/1440 px: нет неявных записей, checkbox не заменяет проверку URL,
  approve передаёт показанный hash один раз, после применения кнопка исчезает,
  горизонтального переполнения/JS ошибок нет. Настоящая LoginPage сохраняет
  согласование/consent после входа; обычный вход остаётся /chats, внешнего redirect нет.
- Регрессионные UI-сценарии: гембл-офферы/финансы, постбэки обоих форматов,
  ручная сверка доставки. Production frontend пересобран.

## Воспроизведение

Не подставлять сюда production URL. Каждый PostgreSQL fixture создаёт отдельную
схему и удаляет её после проверки. Redis должен быть одноразовым.

```sh
env DATABASE_URL=<local-qa-postgresql+asyncpg-url> \
  CRM_TEST_POSTGRES_URL=<same-local-qa-url> \
  REDIS_URL=<local-qa-redis-url> CRM_TEST_REDIS_URL=<same-local-qa-url> \
  .venv/bin/python -m pytest -q tests/test_cloud_assistant.py
```

Для общего регресса с теми же переменными: `.venv/bin/python -m pytest -q`.
Для bridge — отдельный venv с `assistant_bridge/requirements.txt`, НЕ устанавливать
его зависимости поверх CRM; запустить `python -m assistant_bridge.contract_checks`.

Для интерфейса: в `frontend` выполнить `npm run build`; поднять локальный Vite на
свободном порту и выполнить `node frontend/tests/run-cloud-assistant.mjs` из корня.
При необходимости задать CRM_UI_TEST_URL, PLAYWRIGHT_MODULE, CHROMIUM_PATH.
Моки находятся внутри browser runner; это UI-контракт, не вызов живой CRM.

## Границы доказательств

- Это не полноценный тест выбранного ChatGPT workspace. Реальный static OAuth
  client/callback, доступность custom MCP и refresh необходимо проверить отдельно.
- Docker-образ адаптера не собирался и публичный nginx не настраивался. Проверены
  отдельный venv с закреплёнными зависимостями и YAML override, не deployment.
- Не выполнялись restore полной production-выгрузки с 0098, нагрузочный тест на
  production-объёме и измерение изменения p95 основной CRM.
- Полный pytest содержит прежние skipped tests и warnings о multipart/crypt,
  циклических FK в legacy test fixtures. Они не выданы за прошедшие проверки.
- Vite предупреждает о размере общего bundle и возрасте Browserslist. Это не
  ошибка сборки; этот модуль не выполняет несогласованную смену общего сборщика.

Эти пункты — обязательные условия перед включением, а не основание обходить
проверки или утверждать «полностью безопасно в production» по числу unit tests.
