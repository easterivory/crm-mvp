const ru = {
  analytics: 'Аналитика',
  analyticsOverview: 'Аналитика / Обзор',
  bots: 'Боты',
  broadcasts: 'Рассылки',
  cancel: 'Отмена',
  chats: 'Чаты',
  close: 'Закрыть',
  create: 'Создать',
  createLink: 'Создать ссылку',
  docs: 'Документация',
  funnels: 'Воронки',
  leads: 'Лиды',
  loading: 'Загрузка',
  logout: 'Выйти',
  noData: 'Данных пока нет',
  project: 'Проект',
  refresh: 'Обновить',
  save: 'Сохранить',
  settings: 'Настройки',
  tracking: 'Трекинг',
}

export type RuKey = keyof typeof ru

export function t(key: RuKey) {
  return ru[key]
}

export { ru }
