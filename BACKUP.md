# Database Backups

CRM stores production data in PostgreSQL. The safe backup path is a verified
compressed `pg_dump` SQL archive, not a raw copy of the Docker volume.

## What Is Included

- Scheduled ARQ cron worker: `arq app.workers.backup_worker.WorkerSettings`
- Manual backup command: `python scripts/db_backup.py`
- Manual restore command: `python scripts/db_restore.py`
- Docker volume for local archives: `backups_data` mounted at `/backups`
- Optional Telegram delivery to a private chat/channel
- Optional OpenSSL encryption before local storage and Telegram delivery
- Retention by count and age
- Full gzip-stream and PostgreSQL dump-header verification

## Telegram File Limit

Official Telegram Bot API `sendDocument` uploads are limited to 50 MB. Telegram's
local Bot API server can upload files up to 2000 MB:

- https://core.telegram.org/bots/api#senddocument
- https://core.telegram.org/bots/api#using-a-local-bot-api-server

Because of that, the default `BACKUP_TELEGRAM_MAX_UPLOAD_MB` is `49`. If the
backup grows beyond that, the archive is still created locally, but Telegram
delivery fails loudly and sends a text warning if possible.

For larger Telegram delivery, run a local Bot API server and set:

```env
BACKUP_TELEGRAM_API_BASE_URL=http://telegram-bot-api:8081
BACKUP_TELEGRAM_MAX_UPLOAD_MB=2000
```

## Enable Scheduled Backups

Configure the backup bot token, channel ID, and enabled toggle in
**Settings → System**. The ARQ cron runs daily at 03:00 UTC; the Root account
can enqueue a manual run from the same screen. Storage, retention, encryption,
upload limits and optional delivery fallbacks remain deployment settings:

```env
BACKUP_RETENTION_COUNT=14
BACKUP_RETENTION_DAYS=30
BACKUP_VERIFY=true

BACKUP_TELEGRAM_BOT_TOKEN=0000000000:replace_me
BACKUP_TELEGRAM_CHAT_ID=-1000000000000
BACKUP_TELEGRAM_API_BASE_URL=https://api.telegram.org
BACKUP_TELEGRAM_MAX_UPLOAD_MB=49
```

For sensitive production data, also set encryption:

```env
BACKUP_ENCRYPTION_KEY=replace_with_a_long_random_passphrase
```

Keep the encryption key outside Git and outside Telegram. Without this key,
`.sql.gz.enc` files cannot be restored.

Apply changes:

```bash
docker compose up -d --build backup
docker compose logs -f backup
```

The deploy script starts the `backup` container together with the main services.
The backup container runs the ARQ worker and waits for cron/manual jobs.

## Manual Backup

Create a backup and send it to Telegram if configured:

```bash
docker compose exec -T backup python scripts/db_backup.py
```

Create a local backup only:

```bash
docker compose exec -T backup python scripts/db_backup.py --no-telegram
```

Machine-readable output:

```bash
docker compose exec -T backup python scripts/db_backup.py --json
```

List local archives:

```bash
docker compose exec -T backup ls -lh /backups
```

## Restore On A New Server

1. Deploy the code and `.env` on the new server.
2. Put the `.sql.gz` or `.sql.gz.enc` backup into `/backups`.
3. Stop services that write to the database:

```bash
docker compose stop api worker backup
```

4. Restore:

```bash
docker compose run --rm backup python scripts/db_restore.py /backups/crm_mvp_YYYYMMDD_HHMMSS_UTC.sql.gz --yes
```

For encrypted backups:

```bash
BACKUP_ENCRYPTION_KEY=replace_with_the_original_passphrase \
docker compose run --rm backup python scripts/db_restore.py /backups/crm_mvp_YYYYMMDD_HHMMSS_UTC.sql.gz.enc --yes
```

5. Apply migrations and start services:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d postgres redis api worker backup
```

## Restore Safety

`db_restore.py` refuses to run without `--yes`. By default it resets the public
schema, then restores through `psql` with `ON_ERROR_STOP=on` so SQL errors abort.
Always verify `DATABASE_URL` before running it.

To restore into a different database:

```bash
docker compose run --rm backup python scripts/db_restore.py /backups/file.sql.gz \
  --database-url postgresql+asyncpg://user:password@postgres:5432/other_db \
  --yes
```

## Recommended Production Routine

- Keep `BACKUP_RUN_ON_STARTUP=true` so every deploy creates a fresh safety point.
- Use the daily ARQ backup at minimum and monitor failed jobs.
- Use `BACKUP_ENCRYPTION_KEY` before sending archives outside the server.
- Periodically test restore into a temporary database. A backup that has never
  been restored is only a hope, not a recovery plan.
