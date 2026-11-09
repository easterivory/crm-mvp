# Облачный помощник: локальная проверка 07.11.2026

## Прямой origin и native client: 09.11.2026

Для отдельного direct HTTPS добавлен optional ASSISTANT_PUBLIC_BASE_URL без
изменения BASE_URL основной CRM. Issuer, consent redirect, approval URL и UI
Origin согласованы; чужой/старый origin при явном override отклоняется.
Без override прежнее поведение сохраняется. Malformed/HTTP/credential/query/
fragment/path/zero-port origins отвергаются. PKCE roundtrip использует новый
issuer; токен не принимается при подмене конфигурации issuer.

Профильные PG проверки native+assistant+direct-origin: 67 passed до добавления
ещё четырёх invalid-origin случаев. После них полный backend с disposable
PostgreSQL/Redis: 1247 passed, 8 skipped, 7 subtests, 243.63s. Три тяжёлых
counter-профиля CRM_LARGE_QA в этом прогоне не включались; не выдавать skips
за проверенные кейсы. Старые dependency/FK warnings сохранены.
API-loopback/bridge/реальный пользовательский login — отдельная live приёмка.
Docker compose override использует новый assistant base для issuer и старый
BASE_URL только как default; resolved config нужно проверить перед доставкой.

Только локальные одноразовые PostgreSQL/Redis и тестовые данные. Production,
Telegram, OpenAI и кабинеты партнёров не вызывались. Включение модуля на сервере
этим документом не разрешается. Памятка настройки: `cloud-assistant-setup.md`.

## Native Codex: дополнительная проверка 08.11.2026

Исправлена только opt-in валидация redirect URI: `allow_loopback_http=true`
разрешает точный `http://127.0.0.1:<фиксированный порт>/<путь>`. Другие HTTP hosts,
localhost/IPv6, отсутствующий/невалидный порт, userinfo/query/fragment, пробелы
и управляющие символы запрещены. HTTPS-клиенты и точное сопоставление callback,
resource, PKCE, одноразового code и issuer сохраняются. Новая миграция не нужна.

Полный регрессионный прогон с одноразовыми PostgreSQL/Redis и CRM_LARGE_QA=1:
**1204 passed, 5 skipped, 7 subtests passed**, 160.00 сек. После сбора тестов
полного прогона добавлены ещё два негативных случая управляющих символов;
финальное состояние повторно проверено профильным запуском
`tests/test_assistant_native_oauth.py tests/test_cloud_assistant.py`:
**56 passed**, без пропусков. Все эти проверки локальные.

Установленный CLI `0.167.0-alpha.3.2` поддерживает pre-registered OAuth и прочитал
изолированный пример native MCP config в отдельном временном CODEX_HOME.
Рабочий пользовательский config/grants не менялись. Это проверка конфигурации,
НЕ настоящий OAuth login, refresh/revoke или наличие инструментов в чате.
DNS/TLS/production-адаптер и облачный end-to-end тест остаются условиями запуска.
Временные QA PostgreSQL/Redis после проверок остановлены.

## Исходный прогон 07.11.2026

Итог исходного общего прогона: **1160 passed, 5 skipped, 7 subtests passed**
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
