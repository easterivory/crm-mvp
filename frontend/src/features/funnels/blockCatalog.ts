import type { FunnelStepType } from './types'

export type BlockMenuItem = {
  stepType: FunnelStepType
  blockType: string
  label: string
  defaultTitle: string
  defaultConfig?: Record<string, unknown>
  description?: string
  disabled?: boolean
  badge?: string
}

export type UniversalBlock = BlockMenuItem & {
  description: string
}

export type BlockMenuGroup = {
  title: string
  accent?: 'cyan' | 'violet' | 'emerald' | 'amber' | 'rose'
  items: BlockMenuItem[]
}

export const universalBlocks: UniversalBlock[] = [
  {
    stepType: 'trigger',
    blockType: 'generic_trigger',
    label: 'Старт / Триггер',
    defaultTitle: 'Старт',
    description: 'Запускает сценарий: новый чат, /start или ручной запуск.',
    defaultConfig: { trigger_type: 'new_chat' },
  },
  {
    stepType: 'message',
    blockType: 'generic_message',
    label: 'Сообщение',
    defaultTitle: 'Сообщение',
    description: 'Отправляет текст, кнопки или персонализированное сообщение.',
    defaultConfig: {
      message_type: 'text',
      text: 'Введите текст сообщения',
      button_mode: 'inline',
      buttons: [],
      messages: [
        {
          id: 'msg_1',
          type: 'text',
          text: 'Введите текст сообщения',
          delay_seconds: 0,
          button_mode: 'inline',
          buttons: [],
        },
      ],
    },
  },
  {
    stepType: 'input',
    blockType: 'generic_input',
    label: 'Вопрос / сбор данных',
    defaultTitle: 'Вопрос',
    description: 'Задаёт вопрос, валидирует ответ и может сохранить его в лида.',
    defaultConfig: {
      prompt: 'Напишите ответ',
      answer_type: 'text',
      save_to: '',
      wait_for_answer: true,
      delay_before_seconds: 0,
      timeout_seconds: 0,
      max_retries: 2,
      validation: { type: 'text' },
      retry_message: '',
      choices: [],
      button_mode: 'inline',
      timeout_target_step_id: '',
    },
  },
  {
    stepType: 'condition',
    blockType: 'generic_condition',
    label: 'Условие',
    defaultTitle: 'Условие',
    description: 'Проверяет одно или несколько условий и ведёт по исходам.',
    defaultConfig: {
      mode: 'simple_yes_no',
      conditions: [{ id: 'cond_1', source: 'last_answer', field: '', operator: 'equals', value: 'yes' }],
      outcomes: [
        { id: 'true', label: 'Да', target_step_id: '' },
        { id: 'false', label: 'Нет', target_step_id: '' },
        { id: 'fallback', label: 'Fallback', target_step_id: '' },
      ],
    },
  },
  {
    stepType: 'condition',
    blockType: 'generic_hold_router',
    label: 'Hold: сегодня/завтра',
    defaultTitle: 'Hold-режим',
    description: 'Проверяет toggle воронки: Hold включён ведёт в ветку завтра, выключен — сегодня.',
    defaultConfig: {
      mode: 'hold_mode',
      set_call_time: true,
      today_label: 'Сегодня',
      tomorrow_label: 'Завтра',
      conditions: [{ id: 'cond_hold', source: 'hold_mode', field: '', operator: 'equals', value: 'true' }],
      outcomes: [
        { id: 'true', label: 'Hold включён · завтра', target_step_id: '' },
        { id: 'false', label: 'Hold выключен · сегодня', target_step_id: '' },
      ],
    },
  },
  {
    stepType: 'condition',
    blockType: 'generic_ab_test',
    label: 'A/B тест',
    defaultTitle: 'A/B тест',
    description: 'Делит трафик по вариантам и ведёт в разные ветки воронки.',
    defaultConfig: {
      mode: 'ab_test',
      variants: [
        { id: 'a', label: 'Вариант A', weight: 50, target_step_id: '' },
        { id: 'b', label: 'Вариант B', weight: 50, target_step_id: '' },
      ],
    },
  },
  {
    stepType: 'action',
    blockType: 'generic_crm_action',
    label: 'CRM-действие',
    defaultTitle: 'CRM-действие',
    description: 'Выполняет одно или несколько CRM-действий.',
    defaultConfig: { actions: [{ id: 'action_1', type: 'set_lead_status', status: 'in_progress' }] },
  },
  {
    stepType: 'action',
    blockType: 'set_lead_status',
    label: 'Статус лида',
    defaultTitle: 'Статус лида',
    description: 'Меняет статус лида в понятной точке сценария.',
    defaultConfig: { status: 'in_progress' },
  },
  {
    stepType: 'delay',
    blockType: 'generic_delay',
    label: 'Таймер / ожидание',
    defaultTitle: 'Ожидание',
    description: 'Ждёт минуты/часы или обрабатывает таймаут ответа.',
    defaultConfig: { delay_type: 'wait', delay_seconds: 600, target_step_id: '' },
  },
  {
    stepType: 'operator',
    blockType: 'generic_operator',
    label: 'Оператор',
    defaultTitle: 'Оператор',
    description: 'Передаёт диалог оператору или возвращает в бота.',
    defaultConfig: { operator_action: 'handoff' },
  },
  {
    stepType: 'operator',
    blockType: 'manager_review',
    label: 'Проверка менеджером',
    defaultTitle: 'Проверка менеджером',
    description: 'Ставит сценарий на паузу до апрува или возврата менеджером на выбранный шаг.',
    defaultConfig: { message_text: '', set_manual_status: true },
  },
  {
    stepType: 'integration',
    blockType: 'generic_integration',
    label: 'Интеграция',
    defaultTitle: 'Интеграция',
    description: 'Выполняет настроенный webhook или HTTP-запрос.',
    defaultConfig: { integration_type: 'webhook', url: '' },
  },
  {
    stepType: 'finish',
    blockType: 'generic_finish',
    label: 'Завершение',
    defaultTitle: 'Завершение',
    description: 'Останавливает сценарий или завершает его с результатом.',
    defaultConfig: { result: 'stop', set_lead_status: true },
  },
]

export const blockGroups: BlockMenuGroup[] = [
  {
    title: 'Базовые',
    accent: 'cyan',
    items: universalBlocks.filter((item) =>
      ['generic_trigger', 'generic_message', 'generic_input', 'generic_delay'].includes(item.blockType),
    ),
  },
  {
    title: 'Логика',
    accent: 'amber',
    items: [
      universalBlocks.find((item) => item.blockType === 'generic_condition') as UniversalBlock,
      universalBlocks.find((item) => item.blockType === 'generic_hold_router') as UniversalBlock,
      universalBlocks.find((item) => item.blockType === 'generic_ab_test') as UniversalBlock,
    ],
  },
  {
    title: 'CRM',
    accent: 'emerald',
    items: universalBlocks.filter((item) =>
      ['generic_crm_action', 'set_lead_status', 'generic_operator', 'manager_review', 'generic_finish'].includes(
        item.blockType,
      ),
    ),
  },
]

export const legacyBlockGroups: BlockMenuGroup[] = [
  {
    title: 'Триггер',
    items: [
      { stepType: 'trigger', blockType: 'generic_trigger', label: 'Универсальный триггер', defaultTitle: 'Старт' },
      { stepType: 'trigger', blockType: 'new_chat', label: 'Новый чат', defaultTitle: 'Новый чат' },
      { stepType: 'trigger', blockType: 'start_command', label: '/start', defaultTitle: '/start' },
      { stepType: 'trigger', blockType: 'start_with_ref_code', label: '/start с ref-кодом', defaultTitle: '/start с ref-кодом' },
      { stepType: 'trigger', blockType: 'manual_operator_start', label: 'Ручной запуск', defaultTitle: 'Ручной запуск' },
    ],
  },
  {
    title: 'Сообщение',
    items: [
      { stepType: 'message', blockType: 'generic_message', label: 'Универсальное сообщение', defaultTitle: 'Сообщение' },
      { stepType: 'message', blockType: 'send_text', label: 'Текст', defaultTitle: 'Сообщение', defaultConfig: { text: 'Введите текст сообщения' } },
      { stepType: 'message', blockType: 'send_inline_buttons', label: 'Текст + кнопки', defaultTitle: 'Сообщение с кнопками', defaultConfig: { text: 'Выберите вариант', buttons: ['Да', 'Нет'] } },
      { stepType: 'message', blockType: 'send_personalized_message', label: 'Персонализация', defaultTitle: 'Персональное сообщение', defaultConfig: { text: 'Здравствуйте, {{name}}' } },
      { stepType: 'message', blockType: 'notify_manager', label: 'Уведомить менеджера', defaultTitle: 'Уведомить менеджера' },
      { stepType: 'message', blockType: 'notify_admin_chat', label: 'Уведомить админ-чат', defaultTitle: 'Уведомить админ-чат' },
    ],
  },
  {
    title: 'Вопрос',
    items: [
      { stepType: 'input', blockType: 'generic_input', label: 'Универсальный вопрос', defaultTitle: 'Вопрос' },
      { stepType: 'input', blockType: 'ask_name', label: 'Имя', defaultTitle: 'Спросить имя' },
      { stepType: 'input', blockType: 'ask_phone', label: 'Телефон', defaultTitle: 'Спросить телефон' },
      { stepType: 'input', blockType: 'ask_age', label: 'Возраст', defaultTitle: 'Спросить возраст' },
      { stepType: 'input', blockType: 'ask_country', label: 'Страна', defaultTitle: 'Спросить страну' },
      { stepType: 'input', blockType: 'ask_call_time', label: 'Время созвона', defaultTitle: 'Время созвона' },
      { stepType: 'input', blockType: 'ask_text', label: 'Текст', defaultTitle: 'Текстовый вопрос' },
      { stepType: 'input', blockType: 'ask_choice', label: 'Выбор', defaultTitle: 'Выбор из списка' },
      { stepType: 'input', blockType: 'ask_number', label: 'Число', defaultTitle: 'Спросить число' },
      { stepType: 'input', blockType: 'ask_date', label: 'Дата', defaultTitle: 'Спросить дату' },
      { stepType: 'input', blockType: 'ask_time', label: 'Время', defaultTitle: 'Спросить время' },
      {
        stepType: 'input',
        blockType: 'ask_expected_start_amount',
        label: 'Сумма для старта',
        defaultTitle: 'Ожидаемая сумма для старта',
        defaultConfig: {
          prompt: 'С какой суммы планируете начать?',
          answer_type: 'number',
          save_to: 'expected_start_amount',
          wait_for_answer: true,
          validation: { type: 'number' },
        },
      },
    ],
  },
  {
    title: 'Условие',
    items: [
      { stepType: 'condition', blockType: 'generic_condition', label: 'Универсальное условие', defaultTitle: 'Условие' },
      { stepType: 'condition', blockType: 'generic_hold_router', label: 'Hold: сегодня/завтра', defaultTitle: 'Hold-режим' },
      { stepType: 'condition', blockType: 'generic_ab_test', label: 'A/B тест', defaultTitle: 'A/B тест' },
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
    title: 'CRM-действие',
    items: [
      { stepType: 'action', blockType: 'generic_crm_action', label: 'Универсальное CRM-действие', defaultTitle: 'CRM-действие' },
      { stepType: 'action', blockType: 'add_tag', label: 'Добавить тег', defaultTitle: 'Добавить тег' },
      { stepType: 'action', blockType: 'remove_tag', label: 'Удалить тег', defaultTitle: 'Удалить тег' },
      { stepType: 'action', blockType: 'set_lead_status', label: 'Изменить статус', defaultTitle: 'Изменить статус' },
      { stepType: 'action', blockType: 'assign_operator', label: 'Назначить оператора', defaultTitle: 'Назначить оператора' },
      { stepType: 'action', blockType: 'write_field', label: 'Записать поле', defaultTitle: 'Записать поле' },
      { stepType: 'action', blockType: 'submit_to_partner', label: 'Отправить в partner CRM', defaultTitle: 'Отправка в CRM' },
    ],
  },
  {
    title: 'Прочее',
    items: [
      { stepType: 'delay', blockType: 'generic_delay', label: 'Таймер', defaultTitle: 'Ожидание' },
      { stepType: 'operator', blockType: 'generic_operator', label: 'Оператор', defaultTitle: 'Оператор' },
      { stepType: 'operator', blockType: 'manager_review', label: 'Проверка менеджером', defaultTitle: 'Проверка менеджером' },
      { stepType: 'integration', blockType: 'generic_integration', label: 'Интеграция', defaultTitle: 'Интеграция' },
      { stepType: 'finish', blockType: 'generic_finish', label: 'Завершение', defaultTitle: 'Завершение' },
    ],
  },
]

export const mvpBlockTypes = new Set(
  legacyBlockGroups.flatMap((group) => group.items.map((item) => item.blockType)),
)

export function getBlockLabel(blockType: string) {
  return (
    legacyBlockGroups
      .flatMap((group) => group.items)
      .find((item) => item.blockType === blockType)?.label ?? blockType
  )
}

export function getUniversalBlock(stepType: FunnelStepType) {
  return universalBlocks.find((item) => item.stepType === stepType)
}
