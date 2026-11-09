# Облачный помощник: безопасное подключение на MAIN

## Уточнение 09.11.2026: прямой транспорт

Пользователь согласовал direct assistant.sfera.cyou без Bunny, включая раскрытие
IP MAIN. Это заменяет нижеследующий план приёмки CDN, а не ослабляет TLS:
trusted certificate на MAIN, точный hostname, direct verified checks, no-store.
Новая настройка ASSISTANT_PUBLIC_BASE_URL=https://assistant.sfera.cyou отделяет
issuer/consent/approval/UI Origin от BASE_URL основной CRM. BASE_URL не менять.
Проверить реальный frontend bundle: API URL должен оставаться same-origin.
Login, settings/consent, нужные static/auth/assistant API и /mcp должны быть
доступны по direct HTTPS; прочие маршруты отдельного hostname закрыть.
Доставка нового optional base helper вместе с native OAuth patch только API,
без миграций/остановки jobs; rollback к bede25d, не к старому counter baseline.
До QA/сертификата/маршрутов флаги остаются выключенными.

Инструкция сверена с кодом `b7a32b6` 08.11.2026. Это план работ, а не разрешение
на их выполнение. Здесь не выполняются обновление CRM, включение приёмника
постбэков, публикация воронок или тестовые конверсии. Никаких команд из этого
файла не запускать автоматически после получения его другим диалогом.

## Проверка реальной инфраструктуры 08.11.2026

Пилот подтверждён пользователем: superadmin@testcrm.dev, только «Ру гембл»;
клиент — отдельный чат Codex. Доступ к Bunny DNS/CDN у пользователя.
Подтверждена единственная API-реплика, b7a32b6/0098. Помощник не включён.

На исходном preflight nginx слушал только 80, сертификатов/ACME не было.
После явного разрешения пользователя выпуска без email серверный диалог
подготовил origin TLS: доверенный Let's Encrypt, SAN sfera.cyou, срок до
06.02.2027 13:33 МСК. Отдельный listener 443 принимает только этот SNI;
assistant.sfera.cyou и lp.sfera.cyou на нём пока отклоняются. Локальные и внешние
проверки с верификацией сертификата (health, SPA/login, JS/CSS) прошли.
Timer автопродления включён; dry-run с deploy-hook проверил nginx -t и graceful
reload. Перезапуска контейнеров, изменения .env и переключения Bunny не было.
HTTP80/его default server сохранены, редиректов не добавлено; добавлен только
изолированный ACME webroot. Рекламные ссылки, refs/invites и lp не менялись.

Hostname assistant.sfera.cyou ещё не создан. MAIN не имеет глобального IPv6;
не добавлять AAAA по адресу CDN. Ни новый сертификат, ни его внешняя проверка
не доказывают совместимость Bunny IP-origin с SNI/проверкой имени сертификата.

DNS-only A раскрывает origin IP. Не предлагать его как безусловный вариант,
если требуется сохранить сокрытие origin. Для варианта с Bunny CDN точная
DNS-цель берётся из согласованной Pull Zone, не выдумывается.

Скрин пользователя подтвердил текущую Bunny zone sfera.cyou: HTTP origin, порт
80, Verify origin SSL certificate выключен, Forward host header включён,
Follow redirects выключен. Эти параметры НЕ менялись. Cache/WAF/edge rules
целиком ещё не проверены. Ключи, userinfo/авторизацию в URL и токены скрывать.
По одному HTTPS на стороне клиента нельзя объявить Bunny → MAIN зашифрованным.

Следующий gate: отдельно согласованный canary в новой зоне, без переключения
рабочей sfera.cyou. Правильное имя должно проходить с verify ON, неверное имя
сертификата — отклоняться. Один отказ nginx ssl_reject_handshake для неверного
SNI не является доказательством проверки имени сертификата клиентом Bunny.
Параметры новой зоны и полнота защищённого OAuth/consent ещё не подтверждены.
Трёх узких префиксов недостаточно: общая CRM UI передаёт JWT и по другим API.

Пользователь создал отдельную Pull Zone `sferaassistant.b-cdn.net`, ID 6960385,
Origin URL https://31.57.219.146, предписанный Host header sfera.cyou. Первые
анонимные GET /health показали опасный default cache 2592000s: первый MISS,
повторный HIT с тем же x-request-id, без нового origin-запроса. JWT/cookies
туда не отправлялись. Пользователь затем подтвердил Override Cache Time=0
для Request URL `*`, Purge Cache новой зоны и Verify origin SSL certificate=ON.
08.11.2026 17:40:43 МСК два новых /health дали 200/BYPASS с разными x-request-id:
98551b7d752e45688ffb9df6bc315e4f и 535638e673894789b7d3f22ca093c5a7.
Ответы пока имеют Cache-Control public,max-age=0, не no-store. До OAuth/MCP
нужно отдельно проверить no-store на чувствительных маршрутах. Эти результаты
подтверждают bypass, но НЕ отрицательную проверку имени сертификата Bunny.
Рабочая zone 5831320 sfera.cyou, её Origin/кэш, lp, API flags и данные не менялись.

Изолированный временный QA-vhost подготовлен серверным диалогом:
`assistant.sfera.cyou:443`, файл `/etc/nginx/conf.d/crm-assistant-tls-canary.conf`.
Он намеренно использует тот же доверенный сертификат с SAN только sfera.cyou,
принимает handshake и отдаёт только GET/HEAD
`/__crm_tls_canary_7ec3ad6aa5e768435e90ac89` (200, no-store); прочее 404,
без proxy/файлов CRM. Прямой контроль с проверкой имени дал hostname mismatch
(код 62); намеренный QA-контроль без проверки вернул только синтетический ответ.
Это НЕ настоящий MCP-vhost, не инструкция использовать отключённую TLS-проверку.
Bunny negative ещё не выполнен: ждёт временного Host Header=assistant.sfera.cyou
только в новой зоне 6960385 при verify ON/cache bypass. Рабочие HTTP/TLS конфиги
не менялись, выполнен только nginx-t/graceful reload, health/login остались OK.
После теста вернуть Host header новой зоны, удалить только проверенный canary
config и выполнить nginx-t/graceful reload; диагностический лог сохранить.

Issuer остаётся https://sfera.cyou/assistant-oauth. Если origin действительно
HTTP, нужен доверенный origin TLS и согласованное переключение нужного маршрута
на HTTPS с проверкой сертификата. Это затрагивает действующий трафик CRM:
подготовить/проверить заранее, отдельно согласовать точную настройку и откат,
не менять общий Origin/редиректы попутно. Одна установка сертификата для MCP
не исправляет транспорт OAuth/consent. До этого gate включение остановлено.

## 1. Исходное состояние и границы

По последнему отчёту диалога основного сервера: установлен `b7a32b6`, применена
`20261107_0098`; помощник выключен, bridge/HTTPS не настроены. Перед работой
подтвердить это заново. Если ревизия, схема или топология отличаются, остановиться
и адаптировать план, а не запускать upgrade/deploy наугад.

**Уточнение для выбранного пользователем настольного Codex:** в `b7a32b6`
нет поддержки HTTP loopback callback. Нужен узкий патч `assistant_oauth.py`
с `allow_loopback_http` и профильными тестами; до его проверки/доставки API
не переключать. Это отдельное согласованное изменение только API-кода, без
миграции или замены рабочих обработчиков. HTTPS-only ChatGPT web этот патч
не требует. Native клиент настраивается по разделу в cloud-assistant-setup.md.

Для этого состояния повторная миграция, frontend build и пересоздание workers
не нужны. При native-патче заранее подготовить проверенный образ API; если
меняется image ID, согласовать именно эту доставку вместо проверки идентичности
image из раздела 7. Не смешивать её с прочими апдейтами. Меняются настройки/API
помощника, отдельный MCP-контейнер
и ограниченные маршруты reverse proxy. PostgreSQL, Redis, worker, jobs, mtproto,
exports, backup, Telegram webhooks и домены лендингов не перенастраиваются.
Не менять `BASE_URL`, `POSTBACK_*`, callback secrets, очередь и `postback_gateway/`.

При единственном API изменение его environment требует пересоздания контейнера:
`restart` не загружает новые значения. Будет короткое окно недоступности API,
включая webhook intake; уже работающие workers не останавливаются. Telegram
обычно повторяет неуспешную доставку, но это не гарантия отсутствия задержек.
Нулевой простой требует отдельно подготовленного и проверенного переключения
между API-репликами. Не внедрять новую репликацию попутно с этим подключением.

## 2. Что согласовать до переключения

- Отдельное разрешение на запуск адаптера, HTTPS и одно пересоздание API.
- Канонический CRM URL; отдельный hostname помощника, например
  `assistant.example.org`, на ОСНОВНОМ сервере. Не hostname postback gateway.
- Один superadmin UUID и один project UUID пилота; email/название не заменяют UUID.
- Реальный целевой облачный клиент/workspace, доступность custom remote MCP,
  его static client ID, точный callback URI и поддерживаемый способ token auth.
- Начальные scopes: `crm.catalog.read crm.configuration.read`. Аналитика,
  диагностика, данные карточек и preparation пока не запрашиваются.
- Согласованное малонагруженное окно и ответственный за наблюдение/отключение.

Сначала проверить возможность регистрации static OAuth в реальном клиенте.
Текущий сервер поддерживает public client с PKCE S256 либо confidential client
с `client_secret_basic`. DCR, CIMD и `client_secret_post` не реализованы.
Если клиент требует их, остановиться: это отдельная доработка, не повод отключать
auth или выдавать модели административный JWT. Callback брать из управления
конкретным подключением, не копировать вслепую из примера в интернете.

## 3. Подготовка без остановки CRM

Серверный диалог фиксирует фактические рабочий каталог, compose project name,
все compose files/overrides, env-file, profiles и текущие image ID. Последний
известный каталог `/opt/crm-mvp-prod`, project `crm-mvp-prod`; это подсказка,
не замена проверки. Не выводить весь `docker inspect`, `.env`, `nginx -T` или
`docker compose config` в чат: они могут содержать credentials/секретные URL.

Завести в Bash две функции с ПОДТВЕРЖДЁННЫМИ аргументами. Пример только для
установки с одним исходным compose-файлом; при наличии overrides добавить ВСЕ:

```bash
cd /opt/crm-mvp-prod
dc() { docker compose --project-name crm-mvp-prod --env-file .env -f docker-compose.yml "$@"; }
dca() { docker compose --project-name crm-mvp-prod --env-file .env -f docker-compose.yml -f docker-compose.assistant.yml --profile assistant "$@"; }
dc ps
dc exec -T api alembic current
dc config --quiet
dca config --quiet
```

`--env-file` задаёт compose interpolation; текущий сервис API также читает
`.env` через `env_file`. Если production использует другой файл/override, проверить
оба источника, не подменять их новым пустым окружением. Отдельный `environment`
в override может иметь приоритет над `.env`.

До изменений сохранить защищённую копию текущих env/proxy config и image ID;
проверить свежий восстанавливаемый off-host бэкап БД. Не делать live restore.
Зафиксировать 10 минут baseline: API p95/5xx, UI чатов, webhook 503, возраст inbox,
очереди, CPU, available RAM, диск и подключения PostgreSQL. При уже растущих
очередях, проблемах БД/диска или нехватке памяти подключение отложить.

Адаптер ограничен 192 MiB/0.5 CPU; это лимит выполнения, НЕ лимит Docker build.
Желательно подготовить образ вне production и доставить утверждённый артефакт.
Если сборка согласована на main, выполнить её до окна переключения, контролируя
CPU/RAM/диск; не совмещать с рассылкой или backup. Не делать pull/build основной CRM.

Assistant добавляет ленивый SQL pool до 2 соединений НА ПРОЦЕСС API, без overflow.
Это сверх уже действующих intake/counter/general pools. Проверить общий бюджет
всех процессов/сервисов относительно max_connections и административного резерва;
не увеличивать max_connections/общий pool в рамках этой настройки.

## 4. Окружение: сначала read-only

Редактировать только перечисленные параметры в существующем защищённом env-файле.
Остальные значения сохранить. Не передавать секреты в чат, shell history или логи.

```dotenv
ASSISTANT_ENABLED=true
ASSISTANT_MCP_ENABLED=true
ASSISTANT_CHANGES_ENABLED=false
ASSISTANT_ALLOWED_USER_IDS=<UUID одного superadmin>
ASSISTANT_ALLOWED_PROJECT_IDS=<UUID одного проекта>
ASSISTANT_MCP_RESOURCE_URL=https://assistant.example.org/mcp
ASSISTANT_OAUTH_CLIENTS_JSON='{"<реальный-static-client-id>":{"redirect_uris":["<точный-callback-URI>"]}}'
```

Это public PKCE-вариант, а не client secret. Для confidential client добавить
`secret_sha256` в запись клиента; сам secret сохранить только в защищённой
настройке клиента. Не использовать произвольный пример client ID как полученный
от облачного клиента. Не добавлять wildcard callback или wildcard allowlists.

`BASE_URL` остаётся прежним CRM URL. Issuer точно равен
`<BASE_URL без конечного слеша>/assistant-oauth`; resource заканчивается `/mcp`
без конечного слеша. `ASSISTANT_INPUT_KEY` для read-only не требуется. Для будущей
подготовки защищённых URL создать отдельный Fernet key в защищённом хранилище
и сохранить внешнюю резервную копию; не переиспользовать SECRET_KEY/relay key.

Проверить, что diff конфигурации содержит только согласованные assistant-поля;
проверку выполнять локально на сервере с редактированным отчётом, не публиковать
весь diff с секретами. После редактирования снова `dc config --quiet` и
`dca config --quiet`.

## 5. Отдельный адаптер: до переключения API

После согласованной подготовки образа:

```bash
dca build assistant-mcp
dca up -d --no-deps --no-build --pull never assistant-mcp
```

Строка build нужна ТОЛЬКО при согласованной сборке на сервере; при доставке
готового образа используется его проверенный compose image reference вместо
повторной сборки. Не запускать `up` без имени сервиса, `--remove-orphans`, `down`,
`down -v` или deploy-dev.sh. Адаптер должен попасть в существующую сеть CRM,
видеть `http://api:8000/api/v1/assistant`, но не иметь credentials БД/Redis,
полного `.env`, Docker socket, volumes или Telegram sessions.

До включения API проверить metadata самого адаптера через loopback:

```bash
curl --fail --silent --show-error --max-time 5 -H 'Host: assistant.example.org' http://127.0.0.1:8114/.well-known/oauth-protected-resource/mcp
```

Ожидается JSON с точными resource/issuer. Проверить фактическую привязку порта:
ТОЛЬКО `127.0.0.1:8114`, не `0.0.0.0`. Пока API выключил assistant, OAuth/tools
должны отказывать в доступе. Это ожидаемо, не причина включать no-auth.

## 6. HTTPS: отдельный vhost, без замены CRM-конфига

Подготовить DNS/TLS существующим методом без остановки nginx. Не использовать
ACME standalone с остановкой веб-сервера. Новый vhost обслуживает только два
точных пути; всё остальное возвращает 404. Ниже location-блоки для УЖЕ
подготовленного TLS server с проверенным server_name и сертификатом:

```nginx
location = /mcp {
    client_max_body_size 64k;
    client_body_timeout 10s;
    proxy_pass http://127.0.0.1:8114;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_connect_timeout 3s;
    proxy_read_timeout 30s;
    proxy_next_upstream off;
    access_log off;
    add_header Cache-Control "no-store" always;
}
location = /.well-known/oauth-protected-resource/mcp {
    proxy_pass http://127.0.0.1:8114;
    proxy_set_header Host $host;
    proxy_cache off;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
    proxy_next_upstream off;
    access_log off;
    add_header Cache-Control "no-store" always;
}
location / { return 404; }
```

На КАНОНИЧЕСКОМ CRM hostname должны доходить до существующего API backend,
а не SPA/index.html, четыре маршрута:

- GET `/assistant-oauth/.well-known/oauth-authorization-server`;
- GET `/.well-known/oauth-authorization-server/assistant-oauth`;
- GET `/assistant-oauth/authorize`;
- POST `/assistant-oauth/token`.

Если уже есть правильный proxy, не дублировать location. Если нет, добавить
узкие location к тому же проверенному upstream, что обслуживает API сейчас,
с сохранением URI/query/Authorization и без cache, access log тела/query,
JS challenge, CAPTCHA или автоматического retry POST. Ограничить тело token
запроса 8 KiB. Не придумывать новый backend IP/порт. Защитить и error/WAF logs
от записи OAuth code, токенов, query authorize и содержимого tool calls.

Согласовать отдельный rate limit для нового vhost и OAuth-маршрутов, не менять
глобальные лимиты CRM/webhooks. Проверить его на handshake/token refresh, включая
429 и Retry-After; API также имеет собственный limiter. Не включать общий cache.
Оба публичных hostname должны иметь HTTPS и быть доступны целевому клиенту.

Валидировать `nginx -t`. Только при успехе сделать штатный graceful reload,
не restart/stop. Предварительно сохранить vhost; при ошибке теста не reload.

## 7. Единственное переключение API для read-only пилота

Перед переключением проверить, что image reference API из compose разрешается
в тот же image ID, что сейчас исполняется; нет посторонних изменений command,
volumes, ports или environment. Иначе остановиться: это уже не простая настройка.
Адаптер собран/доступен, TLS готов, rollback-конфиг сохранён, мониторинг запущен.

После отдельного подтверждения окна:

```bash
dc up -d --no-deps --no-build --pull never api
```

Не перезапускать worker/jobs/БД/Redis. Не выполнять миграцию, если 0098 уже
подтверждена. `stop_grace_period` у API 60s; длительность недоступности зависит
от завершения запросов и старта процесса. Бюджет и предел ожидания согласовать
до запуска; прежний замер обновления не является SLA для этого переключения.

Сразу проверить публичный `/health`, login/UI, список чатов и фактический новый
intake/прогресс очереди на обычном трафике. `/health` сам по себе не доказывает
работоспособность воронок/чата. При ошибке API сначала прекратить подключение
помощника, восстановить сохранённые assistant-настройки и пересоздать ТОЛЬКО API
тем же образом/ревизией. Не откатывать БД и не сбрасывать pending/review.

## 8. Приёмка до выдачи доступа чату

Проверять последовательно, не запускать массовый нагрузочный тест на prod:

1. Публичная MCP metadata возвращает JSON с правильными resource/issuer;
   обе discovery-ссылки OAuth возвращают правильный JSON, не HTML/redirect-loop.
2. Анонимный MCP initialize с корректными MCP headers/body получает 401 и
   WWW-Authenticate; внешний 8114 закрыт, посторонние пути vhost дают 404.
3. Реальный клиент проходит static OAuth + PKCE и вход в CRM. Consent показывает
   правильные client ID, один проект и ТОЛЬКО два согласованных read scopes.
4. В реальном чате доступны `crm_get_access`, `crm_list_objects`,
   `crm_get_configuration`. Другая project UUID отклоняется. Preparation,
   approve/apply, shell/SQL/send/deploy недоступны. Нет секретов в ответах/логах.
5. После истечения access token проверить refresh в реальном клиенте; затем
   отозвать подключение в CRM и убедиться, что следующий запрос не проходит.
   При несовместимом refresh не отключать проверки, зафиксировать ограничение.
6. Подключить снова только по согласованию. Наблюдать минимум 15 минут:
   baseline CRM, задержки inbox, ошибки intake, SQL connections, RAM и рестарты.
   Пилот: последовательные запросы, без автоопроса/массовой аналитики.

Предлагаемый stop-порог пилота, который надо утвердить заранее: новая
недоступность API/intake, OOM, исчерпание SQL connections либо устойчивое
ухудшение API p95 более чем на 20% за 5 минут при сопоставимой нагрузке.
Малое число запросов не даёт надёжного p95; учитывать очередь и ресурсные метрики.
Не обещать «никак не замедлит»: bounded pools/SQL timeout снижают риск, но
согласованный production baseline обязателен.

## 9. Подготовка изменений: отдельная вторая фаза

После принятого read-only пилота и нового разрешения подготовить
`ASSISTANT_INPUT_KEY`, включить `ASSISTANT_CHANGES_ENABLED` и согласовать ещё одно
пересоздание ТОЛЬКО API (либо совместить с будущим разрешённым обслуживанием).
Затем заново выдать consent со scope `crm.changes.prepare`.

Проверка: одна заявка на выключенный QA-оффер; она ничего не меняет до нативного
согласования. Пользователь открывает CRM, проверяет URL/diff/hash, подтверждает;
повтор не создаёт второй объект. Endpoint/оффер остаются выключенными.
Тестовый объект и проект согласовать заранее. Ни публикации, ни живых конверсий.

V1 не создаёт/клонирует черновик и не редактирует текст/кнопки/`{{offer_link}}`.
Он может назначить уже существующий активный оффер существующему черновику,
но не активировать оффер. Не выдавать пилоту несуществующие возможности.

## 10. Отключение без остановки остальной CRM

При проблеме сначала отозвать соединение в нативной CRM и прекратить внешний
доступ к новому MCP vhost. Затем остановить ТОЛЬКО адаптер:

```bash
dca stop assistant-mcp
```

Это не требует остановки основной CRM; уже начатый запрос может завершаться
до своего timeout. Изменение env на false не действует до пересоздания API:
согласовать его отдельно, если немедленная остановка адаптера/отзыв достаточны.
Возвращать только новые proxy-настройки, не весь nginx из старой копии поверх
последующих изменений. БД/assistant-аудит/лидов/историю/очереди не удалять.

В отчёте сохранить время/длительность окна, ревизию/image ID/миграцию, список
затронутых сервисов, результаты negative tests/refresh/revoke, сравнение baseline,
текущие flags БЕЗ значений секретов и решение: read-only принят / остановлен.

## Ссылки

- Локальная спецификация: `docs/cloud-assistant-setup.md`,
  `docs/cloud-assistant-architecture.md`, `docs/cloud-assistant-qa.md`.
- Официальная инструкция подключения custom MCP (проверена 08.11.2026):
  https://developers.openai.com/api/docs/guides/custom-mcp-server
- OAuth и точный callback целевого подключения:
  https://developers.openai.com/plugins/build/auth

Официальная документация допускает static OAuth credentials; это не заменяет
проверку конкретного workspace/клиента и не означает, что connector автоматически
появится во всех чатах или в другом приложении.
