# 🚀 Настройка деплоя завершена!

## ✅ Что сделано

### 1. SSH доступ
- ✅ SSH ключ добавлен на сервер `codex@45.59.113.248`
- ✅ Беспарольный доступ настроен и работает

### 2. Конфигурация сервера
- ✅ Обновлен `.env` на сервере:
  - `BUILD_FRONTEND_ON_SERVER=1` — фронтенд собирается через Docker
  - `VITE_API_URL=/api/v1` — правильный API endpoint

### 3. GitHub Secrets
- ✅ Добавлены секреты в репозиторий:
  - `SERVER_SSH_KEY` — приватный SSH ключ
  - `SERVER_USER` — codex
  - `SERVER_HOST` — 45.59.113.248

### 4. Локальный деплой скрипт
- ✅ Создан `deploy-local.sh` для ручного деплоя
- ✅ Скрипт протестирован и работает
- ✅ Закоммичен в репозиторий

### 5. Проверка работы
- ✅ Сайт доступен: http://sfera.cyou
- ✅ API работает: http://sfera.cyou/health
- ✅ Контейнеры запущены: api, postgres, redis, worker
- ✅ Последний коммит на сервере: `347fb56`

---

## 📋 Два способа деплоя

### Способ 1: Автоматический (GitHub Actions)
**Статус:** Настроен, но требует проверки

При push в ветку `dev` должен автоматически запускаться деплой через GitHub Actions.

**Проверка:**
1. Откройте: https://github.com/easterivory/crm-mvp/actions
2. Убедитесь, что Actions включены в Settings → Actions → General
3. После push проверьте запуск workflow "Deploy DEV"

**Если не работает:**
- Проверьте, что Actions включены в настройках репозитория
- Проверьте логи в GitHub Actions
- Используйте локальный деплой (способ 2)

### Способ 2: Локальный деплой (работает 100%)
**Статус:** ✅ Работает

Запустите из корня проекта:
```bash
./deploy-local.sh
```

Скрипт:
1. Проверит SSH подключение
2. Подключится к серверу
3. Запустит `/opt/crm-mvp-dev/deploy-dev.sh`
4. Покажет статус деплоя

**Время деплоя:** ~2-3 минуты

---

## 🔧 Что делает deploy-dev.sh на сервере

1. `git fetch origin && git reset --hard origin/dev` — обновление кода
2. Остановка старых контейнеров
3. Сборка и запуск: `docker compose up -d --build`
4. Сборка фронтенда через Docker (если `BUILD_FRONTEND_ON_SERVER=1`)
5. Миграции БД: `alembic upgrade head`
6. Seed тестовых данных (пользователи, бот)
7. Health check

---

## 🌐 Проверка работы

### Frontend
```bash
curl http://sfera.cyou
```
Или откройте в браузере: http://sfera.cyou

### API Health
```bash
curl http://sfera.cyou/health
```
Ожидается: `{"status":"ok","components":{"api":"ok","database":"ok","redis":"ok"}}`

### API Docs
http://sfera.cyou/api/docs

### Контейнеры на сервере
```bash
ssh codex@45.59.113.248 "cd /opt/crm-mvp-dev && docker compose ps"
```

### Логи
```bash
ssh codex@45.59.113.248 "cd /opt/crm-mvp-dev && docker compose logs --tail=50 api"
```

---

## 📝 Тестовые пользователи

После каждого деплоя создаются тестовые пользователи:

- **Super Admin:** `superadmin@testcrm.dev` / `SuperAdminPass123!`
- **Admin:** `admin@testcrm.dev` / `AdminPass123!`
- **Manager:** `manager@testcrm.dev` / `ManagerPass123!`

---

## 🔐 Безопасность

### Что защищено:
- ✅ SSH ключ (не пароль)
- ✅ Секреты в GitHub Secrets (не в коде)
- ✅ `.env` не коммитится в репозиторий

### Что нужно улучшить:
- ⚠️ `SECRET_KEY` в `.env` — заменить на реальный (сейчас `change_me_in_production`)
- ⚠️ HTTPS не настроен (сейчас HTTP)
- ⚠️ Telegram bot token в `.env` — не коммитить в репозиторий
- ⚠️ Для Telegram-бэкапов включить `BACKUP_ENCRYPTION_KEY` в серверном `.env`

---

## 🚀 Следующие шаги

### Обязательно:
1. Настроить HTTPS через Let's Encrypt:
   ```bash
   ssh codex@45.59.113.248
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d sfera.cyou
   ```

2. Заменить `SECRET_KEY` в `.env` на реальный:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

### Опционально:
3. Настроить мониторинг (Sentry, Prometheus)
4. Включить scheduled backup БД по `BACKUP.md`
5. Добавить staging окружение
6. Настроить CI тесты перед деплоем
7. Настроить автоматическую очистку старых Docker образов

---

## 📞 Поддержка

### Проблемы с деплоем:
1. Проверьте логи: `ssh codex@45.59.113.248 "cd /opt/crm-mvp-dev && docker compose logs"`
2. Проверьте контейнеры: `docker compose ps`
3. Перезапустите вручную: `./deploy-local.sh`

### Проблемы с сайтом:
1. Проверьте health: `curl http://sfera.cyou/health`
2. Проверьте nginx: `ssh codex@45.59.113.248 "sudo systemctl status nginx"`
3. Проверьте логи API: `docker compose logs api`

---

## 📊 Текущий статус

- **Сервер:** 45.59.113.248 (Ubuntu, Docker 29.4.1)
- **Домен:** sfera.cyou
- **Путь:** /opt/crm-mvp-dev
- **Ветка:** dev
- **Последний коммит:** 347fb56
- **Контейнеры:** ✅ api, postgres, redis, worker, backup
- **Статус:** ✅ Работает

**Дата настройки:** 2026-05-30
