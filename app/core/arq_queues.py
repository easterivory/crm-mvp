# Keep application jobs on ARQ's historical default so deploys drain work that
# was queued by the previous release. Backup jobs use an isolated queue.
JOBS_QUEUE_NAME = "arq:queue"
BACKUP_QUEUE_NAME = "arq:backup"
