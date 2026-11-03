# Standalone Postback Gateway

Только для отдельного сервера приёма постбэков. Не является сервисом основного compose CRM.

Перед выкаткой прочитать `docs/postback-relay-gateway-server.md` в основном репозитории. Передать этот документ вместе с данной папкой в отдельный диалог.

Приёмник принимает GET и POST (JSON или URL-encoded form) по `/pb/<secret>`, сохраняет запрос в SQLite с WAL/FULL и только после commit возвращает HTTP 200 с `status=accepted` и `delivery_id`. Это подтверждение постановки в очередь, а не успешного сопоставления лида. CRM получает запрос по закрытому соединению и выполняет существующую бизнес-логику.

Список допустимых секретов берётся из CRM каждые 30 секунд в виде SHA-256. Устаревший список (по умолчанию 5 минут) блокирует новый приём ответом 503; уже принятые события сохраняются. Секреты из принятого запроса хранятся в закрытом локальном файле очереди: резервные копии очереди также конфиденциальны.

## Запуск после настройки VPN, firewall и TLS

1. Создать `.env` по `.env.example` с новыми значениями; права 600. Не использовать пример секрета.
2. `docker compose -f compose.gateway.yml up -d --build`
3. `docker compose -f compose.gateway.yml exec gateway python -m postback_gateway.admin stats`
4. Настроить nginx по примеру. Внешний доступ только к HTTPS `/pb/…`, не к служебным маршрутам.

## Эксплуатация

`docker compose -f compose.gateway.yml logs --tail=100 gateway`

`docker compose -f compose.gateway.yml exec gateway python -m postback_gateway.admin dead`

После устранения причины отклонения: `docker compose -f compose.gateway.yml exec gateway python -m postback_gateway.admin retry DELIVERY_UUID`. Повтор использует тот же ID, поэтому повторный commit бизнес-события исключается журналом доставок CRM. Обработанные `unmatched` не отправляются автоматически повторно.

Резервная копия: `docker compose -f compose.gateway.yml exec gateway python -m postback_gateway.admin backup /data/queue-backup.sqlite3`, затем забрать её через `docker compose ... cp`. Не копировать отдельно живой `queue.sqlite3`: часть данных может находиться в WAL. Копию хранить защищённо и убрать с диска после переноса.

Очереди pending/dead не удаляются автоматически. Успешно доставленные локальные записи удаляются через 7 дней. Журнал транспортной идемпотентности CRM не очищать: он нужен и для восстановления старой очереди из бэкапа.

Мониторить: возраст manifest, pending/sending/dead, возраст самого старого pending, свободное место. `/health` проверяет только жизнь процесса. Docker healthcheck использует локальный `/ready`: свежесть manifest, место и лимит очереди; он не доказывает успешную обработку каждого события. При 503/429 партнёр обязан повторить отправку; нельзя возвращать фиктивный 200 при переполнении/недоступности диска.
