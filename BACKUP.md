# Database Backups

CRM stores production data in PostgreSQL. The safe backup path is a verified
`pg_dump` custom-format archive, not a raw copy of the Docker volume.

## What Is Included

- Scheduled backup worker: `python -m app.workers backup`
- Manual backup command: `python scripts/db_backup.py`
- Manual restore command: `python scripts/db_restore.py`
- Docker volume for local archives: `backups_data` mounted at `/backups`
- Optional Telegram delivery to a private chat/channel
- Optional OpenSSL encryption before local storage and Telegram delivery
- Retention by count and age
- Verification with `pg_restore --list`

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

Set these values in the server `.env`:

```env
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_RUN_ON_STARTUP=true
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
`.dump.enc` files cannot be restored.

Apply changes:

```bash
docker compose up -d --build backup
docker compose logs -f backup
```

The deploy script starts the `backup` container together with the main services.
If `BACKUP_ENABLED=false`, the container stays idle.

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
2. Put the `.dump` or `.dump.enc` backup into `/backups`.
3. Stop services that write to the database:

```bash
docker compose stop api worker backup
```

4. Restore:

```bash
docker compose run --rm backup python scripts/db_restore.py /backups/crm_mvp_YYYYMMDD_HHMMSS_UTC.dump --yes
```

For encrypted backups:

```bash
BACKUP_ENCRYPTION_KEY=replace_with_the_original_passphrase \
docker compose run --rm backup python scripts/db_restore.py /backups/crm_mvp_YYYYMMDD_HHMMSS_UTC.dump.enc --yes
```

5. Apply migrations and start services:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d postgres redis api worker backup
```

## Restore Safety

`db_restore.py` refuses to run without `--yes`. By default it passes
`--clean --if-exists` to `pg_restore`, so the target database may be overwritten.
Always verify `DATABASE_URL` before running it.

To restore into a different database:

```bash
docker compose run --rm backup python scripts/db_restore.py /backups/file.dump \
  --database-url postgresql+asyncpg://user:password@postgres:5432/other_db \
  --yes
```

## Recommended Production Routine

- Keep `BACKUP_RUN_ON_STARTUP=true` so every deploy creates a fresh safety point.
- Use daily backups at minimum; use `BACKUP_INTERVAL_HOURS=6` during active launch.
- Use `BACKUP_ENCRYPTION_KEY` before sending archives outside the server.
- Periodically test restore into a temporary database. A backup that has never
  been restored is only a hope, not a recovery plan.
