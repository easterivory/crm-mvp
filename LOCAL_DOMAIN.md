# Локальный запуск на adswiftly.pro

Эти скрипты поднимают текущую локальную версию CRM на `http://adswiftly.pro` без git push/deploy.

## Запуск

Перед запуском открой Docker Desktop.

```bash
./scripts/local-domain-up.sh
```

Что делает команда:

- добавляет `adswiftly.pro` и `www.adswiftly.pro` в `/etc/hosts` на локальный loopback;
- собирает `frontend/dist` из текущих локальных файлов;
- поднимает PostgreSQL, Redis, API и workers через `docker compose`;
- применяет Alembic-миграции;
- запускает Nginx proxy-контейнер на порту `80`.

После запуска открой:

```text
http://adswiftly.pro
```

На первом запуске macOS попросит пароль, чтобы добавить запись в `/etc/hosts`.

## Остановка

```bash
./scripts/local-domain-down.sh
```

Команда остановит proxy-контейнер и локальные контейнеры, но оставит hosts-запись, чтобы следующий запуск был проще.

Чтобы вернуть домен на публичный DNS:

```bash
./scripts/local-domain-down.sh --restore-dns
```

## Полезные опции

```bash
LOCAL_SKIP_FRONTEND_BUILD=1 ./scripts/local-domain-up.sh
LOCAL_PROXY_PORT=8080 ./scripts/local-domain-up.sh
```

Если используешь `LOCAL_PROXY_PORT=8080`, открывай `http://adswiftly.pro:8080`.

Если браузер упрямо открывает HTTPS, явно введи `http://adswiftly.pro`. Для обычного локального теста HTTPS не включается.
