import type { FunnelStepType } from './types'

export type BlockMenuItem = {
  stepType: FunnelStepType
  blockType: string
  label: string
  defaultTitle: string
  defaultConfig?: Record<string, unknown>
}

export type BlockMenuGroup = {
  title: string
  items: BlockMenuItem[]
}

export const blockGroups: BlockMenuGroup[] = [
  {
    title: 'Триггеры',
    items: [
      { stepType: 'trigger', blockType: 'new_chat', label: 'Новый чат', defaultTitle: 'Новый чат' },
      { stepType: 'trigger', blockType: 'start_command', label: '/start', defaultTitle: '/start' },
      { stepType: 'trigger', blockType: 'start_with_ref_code', label: '/start с ref-кодом', defaultTitle: '/start с ref-кодом' },
      { stepType: 'trigger', blockType: 'manual_operator_start', label: 'Ручной запуск', defaultTitle: 'Ручной запуск' },
    ],
  },
  {
    title: 'Сообщения',
    items: [
      { stepType: 'message', blockType: 'send_text', label: 'Текст', defaultTitle: 'Сообщение', defaultConfig: { text: 'Введите текст сообщения' } },
      { stepType: 'message', blockType: 'send_inline_buttons', label: 'Текст + кнопки', defaultTitle: 'Сообщение с кнопками', defaultConfig: { text: 'Выберите вариант', buttons: ['Да', 'Нет'] } },
      { stepType: 'message', blockType: 'send_personalized_message', label: 'Персонализированное сообщение', defaultTitle: 'Персональное сообщение', defaultConfig: { text: 'Здравствуйте, {{name}}' } },
      { stepType: 'message', blockType: 'notify_manager', label: 'Уведомить менеджера', defaultTitle: 'Уведомить менеджера', defaultConfig: { text: 'Нужна реакция менеджера' } },
      { stepType: 'message', blockType: 'notify_admin_chat', label: 'Уведомить админ-чат', defaultTitle: 'Уведомить админ-чат', defaultConfig: { text: 'Новая важная заявка' } },
    ],
  },
  {
    title: 'Сбор данных',
    items: [
      { stepType: 'input', blockType: 'ask_name', label: 'Имя', defaultTitle: 'Спросить имя', defaultConfig: { question_text: 'Как вас зовут?' } },
      { stepType: 'input', blockType: 'ask_phone', label: 'Телефон', defaultTitle: 'Спросить телефон', defaultConfig: { question_text: 'Оставьте телефон для связи' } },
      { stepType: 'input', blockType: 'ask_age', label: 'Возраст', defaultTitle: 'Спросить возраст', defaultConfig: { question_text: 'Сколько вам лет?' } },
      { stepType: 'input', blockType: 'ask_country', label: 'Страна', defaultTitle: 'Спросить страну', defaultConfig: { question_text: 'Из какой вы страны?' } },
      { stepType: 'input', blockType: 'ask_call_time', label: 'Время созвона', defaultTitle: 'Время созвона', defaultConfig: { question_text: 'Когда вам удобно созвониться?' } },
      { stepType: 'input', blockType: 'ask_text', label: 'Текстовый ответ', defaultTitle: 'Текстовый вопрос', defaultConfig: { question_text: 'Напишите ответ' } },
      { stepType: 'input', blockType: 'ask_choice', label: 'Выбор из списка', defaultTitle: 'Выбор из списка', defaultConfig: { question_text: 'Выберите вариант', options: ['Вариант 1', 'Вариант 2'] } },
      { stepType: 'input', blockType: 'ask_number', label: 'Число', defaultTitle: 'Спросить число', defaultConfig: { question_text: 'Введите число' } },
      { stepType: 'input', blockType: 'ask_date', label: 'Дата', defaultTitle: 'Спросить дату', defaultConfig: { question_text: 'Выберите дату' } },
      { stepType: 'input', blockType: 'ask_time', label: 'Время', defaultTitle: 'Спросить время', defaultConfig: { question_text: 'Выберите время' } },
    ],
  },
  {
    title: 'Условия',
    items: [
      { stepType: 'condition', blockType: 'button_equals', label: 'По кнопке', defaultTitle: 'Условие по кнопке' },
      { stepType: 'condition', blockType: 'text_contains', label: 'По тексту', defaultTitle: 'Текст содержит' },
      { stepType: 'condition', blockType: 'field_exists', label: 'Поле заполнено', defaultTitle: 'Поле заполнено' },
      { stepType: 'condition', blockType: 'field_empty', label: 'Поле пустое', defaultTitle: 'Поле пустое' },
      { stepType: 'condition', blockType: 'has_tag', label: 'Есть тег', defaultTitle: 'Есть тег' },
      { stepType: 'condition', blockType: 'not_has_tag', label: 'Нет тега', defaultTitle: 'Нет тега' },
      { stepType: 'condition', blockType: 'lead_status_equals', label: 'По статусу лида', defaultTitle: 'Статус лида' },
      { stepType: 'condition', blockType: 'tracking_link_equals', label: 'По tracking link', defaultTitle: 'Tracking link' },
      { stepType: 'condition', blockType: 'source_equals', label: 'По источнику', defaultTitle: 'Источник' },
      { stepType: 'condition', blockType: 'operator_assigned', label: 'Оператор назначен', defaultTitle: 'Оператор назначен' },
      { stepType: 'condition', blockType: 'operator_not_assigned', label: 'Оператор не назначен', defaultTitle: 'Оператор не назначен' },
      { stepType: 'condition', blockType: 'client_no_reply_for', label: 'Нет ответа N минут', defaultTitle: 'Нет ответа' },
      { stepType: 'condition', blockType: 'field_compare', label: 'Сравнение поля', defaultTitle: 'Сравнение поля' },
    ],
  },
  {
    title: 'CRM-действия',
    items: [
      { stepType: 'action', blockType: 'create_lead', label: 'Создать лид', defaultTitle: 'Создать лид' },
      { stepType: 'action', blockType: 'update_lead', label: 'Обновить лид', defaultTitle: 'Обновить лид' },
      { stepType: 'action', blockType: 'set_lead_status', label: 'Изменить статус', defaultTitle: 'Изменить статус' },
      { stepType: 'action', blockType: 'add_tag', label: 'Добавить тег', defaultTitle: 'Добавить тег' },
      { stepType: 'action', blockType: 'remove_tag', label: 'Удалить тег', defaultTitle: 'Удалить тег' },
      { stepType: 'action', blockType: 'clear_tags', label: 'Очистить теги', defaultTitle: 'Очистить теги' },
      { stepType: 'action', blockType: 'assign_operator', label: 'Назначить оператора', defaultTitle: 'Назначить оператора' },
      { stepType: 'action', blockType: 'unassign_operator', label: 'Снять оператора', defaultTitle: 'Снять оператора' },
      { stepType: 'action', blockType: 'add_note', label: 'Добавить заметку', defaultTitle: 'Добавить заметку' },
      { stepType: 'action', blockType: 'write_field', label: 'Записать поле', defaultTitle: 'Записать поле' },
      { stepType: 'action', blockType: 'attach_tracking_link', label: 'Привязать tracking link', defaultTitle: 'Привязать tracking link' },
      { stepType: 'action', blockType: 'close_chat', label: 'Закрыть чат', defaultTitle: 'Закрыть чат' },
      { stepType: 'action', blockType: 'mark_lost', label: 'Пометить lost', defaultTitle: 'Lost' },
      { stepType: 'action', blockType: 'mark_rejected', label: 'Пометить rejected', defaultTitle: 'Rejected' },
      { stepType: 'action', blockType: 'mark_success', label: 'Пометить success', defaultTitle: 'Success' },
      { stepType: 'action', blockType: 'send_to_crm_placeholder', label: 'Заглушка отправки в CRM', defaultTitle: 'Отправка в CRM' },
    ],
  },
  {
    title: 'Таймеры',
    items: [
      { stepType: 'delay', blockType: 'wait_minutes', label: 'Ждать N минут', defaultTitle: 'Ждать минуты', defaultConfig: { delay_minutes: 10 } },
      { stepType: 'delay', blockType: 'wait_hours', label: 'Ждать N часов', defaultTitle: 'Ждать часы', defaultConfig: { delay_hours: 1 } },
      { stepType: 'delay', blockType: 'wait_for_reply_timeout', label: 'Нет ответа N минут', defaultTitle: 'Таймер без ответа', defaultConfig: { delay_minutes: 30 } },
    ],
  },
  {
    title: 'Оператор',
    items: [
      { stepType: 'operator', blockType: 'handoff_to_operator', label: 'Передать оператору', defaultTitle: 'Передать оператору' },
      { stepType: 'operator', blockType: 'assign_specific_operator', label: 'Назначить конкретного оператора', defaultTitle: 'Конкретный оператор' },
      { stepType: 'operator', blockType: 'assign_random_operator', label: 'Назначить случайного оператора', defaultTitle: 'Случайный оператор' },
      { stepType: 'operator', blockType: 'notify_operator', label: 'Уведомить оператора', defaultTitle: 'Уведомить оператора' },
      { stepType: 'operator', blockType: 'stop_bot_for_operator', label: 'Остановить бота', defaultTitle: 'Остановить бота' },
      { stepType: 'operator', blockType: 'return_to_bot', label: 'Вернуть в бота', defaultTitle: 'Вернуть в бота' },
      { stepType: 'operator', blockType: 'close_dialog', label: 'Закрыть диалог', defaultTitle: 'Закрыть диалог' },
      { stepType: 'operator', blockType: 'open_dialog', label: 'Открыть диалог', defaultTitle: 'Открыть диалог' },
    ],
  },
  {
    title: 'Интеграции',
    items: [
      { stepType: 'integration', blockType: 'outgoing_webhook', label: 'Webhook', defaultTitle: 'Webhook' },
      { stepType: 'integration', blockType: 'http_request', label: 'HTTP request', defaultTitle: 'HTTP request' },
      { stepType: 'integration', blockType: 'external_crm_placeholder', label: 'Внешняя CRM placeholder', defaultTitle: 'Внешняя CRM' },
    ],
  },
  {
    title: 'Завершение',
    items: [
      { stepType: 'finish', blockType: 'stop_scenario', label: 'Остановить сценарий', defaultTitle: 'Остановить сценарий' },
      { stepType: 'finish', blockType: 'finish_success', label: 'Успешно завершить', defaultTitle: 'Success' },
      { stepType: 'finish', blockType: 'finish_lost', label: 'Завершить как lost', defaultTitle: 'Lost' },
      { stepType: 'finish', blockType: 'finish_rejected', label: 'Завершить как rejected', defaultTitle: 'Rejected' },
    ],
  },
]

export const mvpBlockTypes = new Set(
  blockGroups.flatMap((group) => group.items.map((item) => item.blockType)),
)

export function getBlockLabel(blockType: string) {
  return (
    blockGroups
      .flatMap((group) => group.items)
      .find((item) => item.blockType === blockType)?.label ?? blockType
  )
}
