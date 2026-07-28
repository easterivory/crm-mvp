from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal

from app.core.telegram_commands import (
    CUSTOM_COMMAND_TRIGGER_TYPE,
    TELEGRAM_COMMAND_RE,
    normalize_telegram_command,
)
from app.schemas.funnel import FunnelBlockDefinitionOut, FunnelBlockRegistryOut


BlockStatus = Literal["mvp", "supported", "reserved"]


@dataclass(frozen=True)
class BlockDefinition:
    step_type: str
    block_type: str
    label: str
    status: BlockStatus = "supported"
    description: str | None = None


LEAD_FIELD_KEYS = [
    "name",
    "first_name",
    "last_name",
    "username",
    "phone",
    "age",
    "country",
    "call_time_text",
    "preferred_call_time",
    "call_date",
    "call_time_from",
    "call_time_to",
    "has_card",
    "experience",
    "expected_start_amount",
    "status",
    "source",
    "comment",
]

CUSTOM_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


def is_supported_lead_field_key(value: str) -> bool:
    key = value.strip()
    return key in LEAD_FIELD_KEYS or bool(CUSTOM_FIELD_KEY_RE.fullmatch(key))


MVP_BLOCKS: dict[str, list[tuple[str, str]]] = {
    "trigger": [
        ("generic_trigger", "Старт / Триггер"),
        ("new_chat", "Новый чат"),
        ("start_command", "/start"),
        ("start_with_ref_code", "/start с ref-кодом"),
        ("manual_operator_start", "Ручной запуск"),
    ],
    "message": [
        ("generic_message", "Сообщение"),
        ("send_text", "Текст"),
        ("send_inline_buttons", "Текст + кнопки"),
        ("send_personalized_message", "Персонализированное сообщение"),
        ("notify_manager", "Уведомить менеджера"),
        ("notify_admin_chat", "Уведомить админ-чат"),
    ],
    "input": [
        ("generic_input", "Вопрос / сбор данных"),
        ("ask_name", "Имя"),
        ("ask_phone", "Телефон"),
        ("ask_age", "Возраст"),
        ("ask_country", "Страна"),
        ("ask_call_time", "Время созвона"),
        ("ask_text", "Текстовый ответ"),
        ("ask_choice", "Выбор из списка"),
        ("ask_number", "Число"),
        ("ask_date", "Дата"),
        ("ask_time", "Время"),
        ("ask_expected_start_amount", "Ожидаемая сумма для старта"),
    ],
    "condition": [
        ("generic_condition", "Условие"),
        ("button_equals", "По кнопке"),
        ("text_contains", "По тексту"),
        ("field_exists", "Поле заполнено"),
        ("field_empty", "Поле пустое"),
        ("has_tag", "Есть тег"),
        ("not_has_tag", "Нет тега"),
        ("lead_status_equals", "По статусу лида"),
        ("tracking_link_equals", "По tracking link"),
        ("generic_hold_router", "Hold: сегодня/завтра"),
        ("generic_ab_test", "A/B тест"),
        ("source_equals", "По источнику"),
        ("operator_assigned", "Оператор назначен"),
        ("operator_not_assigned", "Оператор не назначен"),
        ("client_no_reply_for", "Нет ответа N минут"),
        ("field_compare", "Сравнение поля"),
        ("confidence_score", "Уверенность лида"),
    ],
    "action": [
        ("generic_crm_action", "CRM-действие"),
        ("create_lead", "Создать лид"),
        ("update_lead", "Обновить лид"),
        ("set_lead_status", "Изменить статус"),
        ("add_tag", "Добавить тег"),
        ("remove_tag", "Удалить тег"),
        ("clear_tags", "Очистить теги"),
        ("assign_operator", "Назначить оператора"),
        ("unassign_operator", "Снять оператора"),
        ("add_note", "Добавить заметку"),
        ("write_field", "Записать поле"),
        ("attach_tracking_link", "Привязать tracking link"),
        ("close_chat", "Закрыть чат"),
        ("mark_lost", "Пометить lost"),
        ("mark_rejected", "Пометить rejected"),
        ("mark_success", "Пометить success"),
        ("submit_to_partner", "Отправить в partner CRM"),
        ("record_lead_event", "Записать событие лида"),
    ],
    "delay": [
        ("generic_delay", "Таймер / ожидание"),
        ("wait_minutes", "Ждать N минут"),
        ("wait_hours", "Ждать N часов"),
        ("wait_for_reply_timeout", "Нет ответа N минут"),
    ],
    "operator": [
        ("generic_operator", "Оператор"),
        ("manager_review", "Передать менеджеру на проверку"),
        ("handoff_to_operator", "Передать оператору"),
        ("assign_specific_operator", "Назначить конкретного оператора"),
        ("assign_random_operator", "Назначить случайного оператора"),
        ("notify_operator", "Уведомить оператора"),
        ("stop_bot_for_operator", "Остановить бота"),
        ("return_to_bot", "Вернуть в бота"),
        ("close_dialog", "Закрыть диалог"),
        ("open_dialog", "Открыть диалог"),
    ],
    "integration": [
        ("generic_integration", "Интеграция"),
        ("ai_response", "ИИ-ответ"),
        ("outgoing_webhook", "Webhook"),
        ("http_request", "HTTP request"),
        ("external_crm", "Внешняя CRM"),
    ],
    "finish": [
        ("generic_finish", "Завершение"),
        ("stop_scenario", "Остановить сценарий"),
        ("finish_success", "Успешно завершить"),
        ("finish_lost", "Завершить как lost"),
        ("finish_rejected", "Завершить как rejected"),
    ],
}


SUPPORTED_EXTRA_BLOCKS: dict[str, list[str]] = {
    "trigger": [
        "first_user_message",
        "button_clicked",
        "user_text_answer",
        "tag_assigned",
        "tag_removed",
        "lead_status_changed",
        "lead_entered_funnel_stage",
        "dialog_closed",
        "dialog_reopened",
        "operator_assigned",
        "operator_changed",
        "client_no_reply_timeout",
        "operator_no_reply_timeout",
        "user_subscribed",
        "user_unsubscribed",
        "schedule_trigger",
        "webhook_trigger",
        "external_api_request",
        "payment_created",
        "payment_success",
        "payment_failed",
        "form_submitted",
        "mini_landing_opened",
        "product_selected",
    ],
    "message": [
        "send_photo",
        "send_video",
        "send_voice",
        "send_video_note",
        "send_file",
        "send_link",
        "send_product_card",
        "send_gallery",
        "send_reply_buttons",
        "send_template",
        "notify_operator",
        "notify_admin_chat",
        "send_email",
        "send_sms",
        "send_whatsapp",
    ],
    "input": [
        "ask_email",
        "ask_telegram_username",
        "ask_city",
        "ask_budget",
        "ask_comment",
        "ask_file",
        "save_answer_to_lead_field",
        "save_answer_to_chat_field",
        "save_answer_to_custom_field",
        "validate_answer",
        "retry_question",
        "skip_question",
    ],
    "condition": [
        "text_equals",
        "funnel_stage_equals",
        "is_new_client",
        "is_returning_client",
        "client_exists",
        "is_working_time",
        "is_not_working_time",
        "weekday_equals",
        "user_subscribed_to_channel",
        "payment_success",
        "payment_failed",
        "user_in_segment",
    ],
    "action": [
        "create_chat",
        "update_chat",
        "transfer_to_department",
        "set_funnel_stage",
        "create_task",
        "create_reminder",
        "change_source",
        "detach_tracking_link",
        "mark_chat_active",
        "block_client",
        "unblock_client",
    ],
    "delay": [
        "wait_seconds",
        "wait_until_time",
        "wait_until_working_time",
        "wait_until_weekday",
        "no_reply_go_to_block",
        "reply_continue",
        "delayed_message",
        "interval_touch_series",
        "stop_timer_on_client_reply",
    ],
    "operator": [
        "put_chat_in_queue",
        "assign_by_load",
        "assign_by_project",
        "assign_by_source",
        "assign_by_tag",
        "assign_by_language",
        "continue_bot_with_operator",
        "set_sla_timer",
        "escalate_if_operator_no_reply",
    ],
    "integration": [
        "incoming_webhook",
        "google_sheets",
        "amocrm",
        "bitrix24",
        "hubspot",
        "payment_provider",
        "calendar",
        "email_service",
        "sms_service",
        "whatsapp",
        "instagram",
        "vk",
        "analytics_integration",
        "ads_integration",
        "make",
        "albato",
        "zapier",
        "external_api_send",
        "external_api_fetch",
    ],
    "finish": [],
}


RESERVED_FUTURE_BLOCKS = [
    "ai_classify_lead",
    "ai_summarize_chat",
    "ai_extract_fields",
    "ai_generate_funnel",
    "ai_audit_funnel",
    "ai_suggest_funnel_improvements",
    "ai_operator_quality_control",
    "smart_lead_distribution",
    "sla_escalation",
    "payment_blocks",
    "product_catalog_blocks",
    "mini_landing_blocks",
    "ab_branch",
    "scenario_analytics_heatmap",
    "version_rollback",
    "test_simulator",
    "predictive_sale_probability",
    "source_creative_budget_recommendations",
]


class FunnelBlockRegistry:
    allowed_step_types = tuple(MVP_BLOCKS.keys())

    def __init__(self) -> None:
        self._blocks = self._build_blocks()
        self._lookup = {
            (definition.step_type, definition.block_type): definition
            for blocks in self._blocks.values()
            for definition in blocks
        }

    def as_schema(self) -> FunnelBlockRegistryOut:
        return FunnelBlockRegistryOut(
            allowed_step_types=list(self.allowed_step_types),
            lead_field_keys=LEAD_FIELD_KEYS,
            reserved_future_blocks=RESERVED_FUTURE_BLOCKS,
            blocks={
                step_type: [
                    FunnelBlockDefinitionOut(
                        step_type=item.step_type,
                        block_type=item.block_type,
                        label=item.label,
                        status=item.status,
                        description=item.description,
                    )
                    for item in blocks
                ]
                for step_type, blocks in self._blocks.items()
            },
        )

    def is_known(self, step_type: str, block_type: str) -> bool:
        return (step_type, block_type) in self._lookup

    def is_mvp(self, block_type: str) -> bool:
        return any(
            definition.block_type == block_type and definition.status == "mvp"
            for blocks in self._blocks.values()
            for definition in blocks
        )

    def is_reserved(self, block_type: str) -> bool:
        return any(
            definition.block_type == block_type and definition.status == "reserved"
            for blocks in self._blocks.values()
            for definition in blocks
        )

    def validate_block(self, step_type: str, block_type: str, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if step_type not in self.allowed_step_types:
            return [f"Неизвестная категория блока: {step_type}."]
        if not self.is_known(step_type, block_type):
            return [f"Блок {block_type} не разрешён для категории {step_type}."]

        if block_type == "generic_trigger":
            trigger_type = str(config.get("trigger_type") or "new_chat").strip()
            if trigger_type not in {
                "new_chat",
                "start_command",
                "start_with_ref_code",
                "manual_operator_start",
                CUSTOM_COMMAND_TRIGGER_TYPE,
            }:
                errors.append("Выберите допустимый тип триггера.")
            if trigger_type == CUSTOM_COMMAND_TRIGGER_TYPE:
                command = normalize_telegram_command(config.get("command"))
                description = str(config.get("command_description") or "").strip()
                if not TELEGRAM_COMMAND_RE.fullmatch(command):
                    errors.append(
                        "Команда должна содержать 1–32 символа: латинские строчные буквы, "
                        "цифры или подчёркивание."
                    )
                elif command == "start":
                    errors.append("Команда /start зарезервирована для запуска бота.")
                if not description:
                    errors.append("Укажите подпись команды для меню Telegram.")
                elif len(description) > 256:
                    errors.append("Подпись команды не должна превышать 256 символов.")
        if block_type == "generic_message":
            messages = config.get("messages")
            def has_media_payload(message: dict) -> bool:
                media = message.get("media") if isinstance(message.get("media"), dict) else {}
                for key in (
                    "upload_id",
                    "broadcast_upload_id",
                    "telegram_file_id",
                    "file_id",
                    "media_file_id",
                    "photo",
                    "video",
                    "voice",
                    "video_note",
                    "document",
                    "file",
                    "media_url",
                ):
                    value = message.get(key) or media.get(key)
                    if isinstance(value, str) and value.strip():
                        return True
                return False

            has_sequence_text = (
                isinstance(messages, list)
                and any(
                    isinstance(message, dict)
                    and str(
                        message.get("text")
                        or message.get("message")
                        or message.get("message_text")
                        or ""
                    ).strip()
                    for message in messages
                )
            )
            has_sequence_media = (
                isinstance(messages, list)
                and any(isinstance(message, dict) and has_media_payload(message) for message in messages)
            )
            has_config_media = has_media_payload(config)
            if (
                not has_sequence_text
                and not has_sequence_media
                and not self._text(config, "text", "message_text")
                and not has_config_media
            ):
                errors.append("Для сообщения нужен текст.")
            buttons = config.get("buttons")
            if buttons is not None and not isinstance(buttons, list):
                errors.append("Кнопки сообщения должны быть списком.")
            if messages is not None and not isinstance(messages, list):
                errors.append("Sequence сообщений должен быть списком.")
        if block_type == "generic_input":
            if not self._text(config, "prompt", "question_text", "text", "message_text"):
                errors.append("Для вопроса нужен текст вопроса.")
            answer_type = str(config.get("answer_type") or "").strip()
            if answer_type not in {"text", "phone", "email", "name", "number", "choice", "date", "time"}:
                errors.append("Для вопроса выберите тип ответа.")
            save_to = str(config.get("save_to") or "").strip()
            custom_field_key = str(config.get("custom_field_key") or "").strip()
            if str(config.get("field_mode") or "").strip() == "custom" and not custom_field_key:
                errors.append("Укажите ключ произвольного поля.")
            if save_to and not is_supported_lead_field_key(save_to):
                errors.append("Поле для сохранения ответа не поддерживается.")
            if custom_field_key and not is_supported_lead_field_key(custom_field_key):
                errors.append(
                    "Ключ произвольного поля должен начинаться с латинской буквы "
                    "и содержать только a-z, 0-9 и подчёркивание."
                )
            if answer_type == "choice" and not self._list(config, "choices", "options", "buttons"):
                errors.append("Для выбора нужен хотя бы один вариант.")
        if block_type in {"generic_condition", "generic_hold_router"}:
            mode = str(config.get("mode") or "all").strip()
            if mode not in {"all", "any", "simple_yes_no", "hold_mode"}:
                errors.append("Режим условия должен быть all, any, simple_yes_no или hold_mode.")
            conditions = config.get("conditions")
            if block_type == "generic_condition" and (
                not isinstance(conditions, list) or not conditions
            ):
                errors.append("Добавьте хотя бы одно условие.")
            elif isinstance(conditions, list):
                for index, condition in enumerate(conditions, start=1):
                    if not isinstance(condition, dict):
                        errors.append(f"Условие #{index} должно быть объектом.")
                        continue
                    condition_type = str(
                        condition.get("type") or condition.get("operator") or condition.get("source") or ""
                    ).strip()
                    if not condition_type:
                        errors.append(f"Условие #{index}: выберите тип.")
            outcomes = config.get("outcomes")
            if outcomes is not None and not isinstance(outcomes, list):
                errors.append("Исходы условия должны быть списком.")
        if block_type == "generic_crm_action":
            actions = config.get("actions")
            if not isinstance(actions, list) or not actions:
                errors.append("Добавьте хотя бы одно CRM-действие.")
            else:
                for index, action in enumerate(actions, start=1):
                    if not isinstance(action, dict) or not str(action.get("type") or "").strip():
                        errors.append(f"CRM-действие #{index}: выберите тип.")
        if block_type == "generic_delay":
            delay_type = str(config.get("delay_type") or "wait").strip()
            if delay_type in {"wait", "no_reply_timeout", "reply_timeout"}:
                if self._positive_number(config, "delay_seconds", "seconds", "minutes", "delay_minutes") is None:
                    errors.append("Укажите задержку больше 0.")
            elif delay_type == "hours":
                if self._positive_number(config, "hours", "delay_hours") is None:
                    errors.append("Укажите задержку в часах больше 0.")
            elif delay_type == "minutes":
                if self._positive_number(config, "minutes", "delay_minutes") is None:
                    errors.append("Укажите задержку в минутах больше 0.")
            else:
                errors.append("Выберите допустимый тип таймера.")
        if block_type == "generic_operator":
            if not self._text(config, "operator_action", "action_type"):
                errors.append("Выберите действие оператора.")
        if block_type == "generic_integration":
            integration_type = str(config.get("integration_type") or "webhook").strip()
            if integration_type in {"webhook", "http_request"} and not self._text(config, "url"):
                errors.append("Для интеграции нужен URL.")
        if block_type == "ai_response":
            if not self._text(config, "step_goal", "goal"):
                errors.append("Для ИИ-ответа укажите цель шага.")
            outcomes = config.get("outcomes")
            if not isinstance(outcomes, list) or not outcomes:
                errors.append("Для ИИ-ответа добавьте хотя бы один маршрут.")
            else:
                route_ids: set[str] = set()
                for index, outcome in enumerate(outcomes, start=1):
                    if not isinstance(outcome, dict):
                        errors.append(f"Маршрут ИИ #{index} должен быть объектом.")
                        continue
                    route_id = str(outcome.get("id") or "").strip()
                    if not route_id:
                        errors.append(f"Маршрут ИИ #{index}: укажите технический ключ.")
                    elif not CUSTOM_FIELD_KEY_RE.fullmatch(route_id):
                        errors.append(
                            f"Маршрут ИИ #{index}: ключ должен содержать только "
                            "a-z, 0-9 и подчёркивание."
                        )
                    elif route_id in route_ids:
                        errors.append(f"Маршрут ИИ «{route_id}» дублируется.")
                    route_ids.add(route_id)
                    if not str(outcome.get("label") or "").strip():
                        errors.append(f"Маршрут ИИ #{index}: укажите название.")
                    instruction = str(
                        outcome.get("instruction")
                        or outcome.get("when")
                        or ""
                    ).strip()
                    if len(instruction) > 1000:
                        errors.append(
                            f"Маршрут ИИ #{index}: правило выбора длиннее 1000 символов."
                        )
                if "fallback" not in route_ids:
                    errors.append("Для ИИ-ответа нужен маршрут fallback.")

            output_fields = config.get("output_fields")
            if output_fields is not None and not isinstance(output_fields, list):
                errors.append("Извлекаемые поля ИИ должны быть списком.")
            elif isinstance(output_fields, list):
                response_keys: set[str] = set()
                for index, field in enumerate(output_fields, start=1):
                    if not isinstance(field, dict):
                        errors.append(f"Извлекаемое поле #{index} должно быть объектом.")
                        continue
                    response_key = str(field.get("response_key") or "").strip()
                    lead_field_key = str(field.get("lead_field_key") or "").strip()
                    if not CUSTOM_FIELD_KEY_RE.fullmatch(response_key):
                        errors.append(
                            f"Извлекаемое поле #{index}: неверный ключ ответа модели."
                        )
                    elif response_key in response_keys:
                        errors.append(
                            f"Извлекаемое поле «{response_key}» дублируется."
                        )
                    response_keys.add(response_key)
                    if not is_supported_lead_field_key(lead_field_key):
                        errors.append(
                            f"Извлекаемое поле #{index}: поле лида не поддерживается."
                        )
                    if str(field.get("value_type") or "text") not in {
                        "text",
                        "number",
                        "boolean",
                    }:
                        errors.append(
                            f"Извлекаемое поле #{index}: выберите допустимый тип."
                        )

            for key, minimum, maximum, label in (
                ("temperature", 0, 2, "temperature"),
                ("max_output_tokens", 1, 32000, "лимит токенов"),
                ("history_message_limit", 1, 100, "глубину истории"),
                ("typing_delay_per_char_ms", 0, 250, "скорость печати"),
                ("min_delay_ms", 0, 30000, "минимальную задержку"),
                ("max_delay_ms", 0, 30000, "максимальную задержку"),
            ):
                if key not in config or config.get(key) in {None, ""}:
                    continue
                try:
                    number = float(config[key])
                except (TypeError, ValueError):
                    errors.append(f"Укажите числовое значение для поля «{label}».")
                    continue
                if number < minimum or number > maximum:
                    errors.append(
                        f"Поле «{label}» должно быть от {minimum} до {maximum}."
                    )
        if block_type == "generic_finish":
            result = str(config.get("result") or "stop").strip()
            if result not in {"success", "lost", "rejected", "stop"}:
                errors.append("Выберите допустимый результат завершения.")

        if block_type in {"send_text", "send_personalized_message", "send_inline_buttons"}:
            if not self._text(config, "text", "message_text"):
                errors.append("Для сообщения нужен текст.")
        if block_type in {"notify_manager", "notify_admin_chat", "notify_operator"}:
            if not self._text(config, "text", "message_text"):
                errors.append("Для уведомления нужен текст.")
        if step_type == "input" and block_type != "generic_input":
            if not self._text(config, "question_text", "text", "message_text"):
                errors.append("Для вопроса нужен текст вопроса.")
            if block_type == "ask_choice" and not self._list(config, "options", "buttons"):
                errors.append("Для выбора нужен хотя бы один вариант.")
        if block_type in {"wait_minutes", "wait_for_reply_timeout", "client_no_reply_for"}:
            if self._positive_number(config, "delay_minutes", "minutes") is None:
                errors.append("Укажите задержку в минутах больше 0.")
        if block_type == "wait_hours":
            if self._positive_number(config, "delay_hours", "hours") is None:
                errors.append("Укажите задержку в часах больше 0.")
        if block_type == "write_field":
            field_key = str(config.get("lead_field_key") or "").strip()
            if not is_supported_lead_field_key(field_key):
                errors.append("Для записи поля выберите допустимое поле лида.")
        if block_type in {"http_request", "outgoing_webhook"}:
            if not self._text(config, "url"):
                errors.append("Для HTTP/Webhook блока нужен URL.")
        return errors

    @staticmethod
    def _build_blocks() -> dict[str, list[BlockDefinition]]:
        blocks: dict[str, list[BlockDefinition]] = {}
        for step_type, items in MVP_BLOCKS.items():
            definitions = [
                BlockDefinition(step_type=step_type, block_type=block_type, label=label, status="mvp")
                for block_type, label in items
            ]
            definitions.extend(
                BlockDefinition(
                    step_type=step_type,
                    block_type=block_type,
                    label=block_type.replace("_", " "),
                    status="supported",
                    description="Зарезервировано в registry; UI v1 показывает как read-only.",
                )
                for block_type in SUPPORTED_EXTRA_BLOCKS.get(step_type, [])
                if block_type not in {item.block_type for item in definitions}
            )
            blocks[step_type] = definitions

        blocks.setdefault("action", []).extend(
            BlockDefinition(
                step_type="action",
                block_type=block_type,
                label=block_type.replace("_", " "),
                status="reserved",
                description="Future/reserved: сохранено в registry, runtime v1 не исполняет.",
            )
            for block_type in RESERVED_FUTURE_BLOCKS
        )
        return blocks

    @staticmethod
    def _text(config: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _list(config: dict[str, Any], *keys: str) -> list[Any] | None:
        for key in keys:
            value = config.get(key)
            if isinstance(value, list) and value:
                return value
        return None

    @staticmethod
    def _positive_number(config: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = config.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
            if isinstance(value, str):
                try:
                    number = float(value)
                except ValueError:
                    continue
                if number > 0:
                    return number
        return None
