import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Bot,
  Calculator,
  CheckCircle2,
  ClipboardList,
  Database,
  FileText,
  Globe2,
  KeyRound,
  Languages,
  Megaphone,
  MessageSquareText,
  MousePointerClick,
  Plug,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Smartphone,
  Table,
  Tags,
  Timer,
  UsersRound,
  Workflow,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

type Tone = 'cyan' | 'emerald' | 'violet' | 'amber' | 'rose' | 'slate'

type NavItem = {
  id: string
  label: string
  icon: LucideIcon
}

type FeatureCard = {
  title: string
  description: string
  icon: LucideIcon
  tone: Tone
  bullets: string[]
}

type Formula = {
  label: string
  value: string
  note: string
}

type LogicFlow = {
  title: string
  icon: LucideIcon
  tone: Tone
  steps: string[]
}

const toneStyles: Record<Tone, { border: string; bg: string; icon: string; text: string }> = {
  cyan: {
    border: 'border-cyan-300/25',
    bg: 'bg-cyan-400/10',
    icon: 'text-cyan-200',
    text: 'text-cyan-100',
  },
  emerald: {
    border: 'border-emerald-300/25',
    bg: 'bg-emerald-400/10',
    icon: 'text-emerald-200',
    text: 'text-emerald-100',
  },
  violet: {
    border: 'border-violet-300/25',
    bg: 'bg-violet-400/10',
    icon: 'text-violet-200',
    text: 'text-violet-100',
  },
  amber: {
    border: 'border-amber-300/25',
    bg: 'bg-amber-400/10',
    icon: 'text-amber-100',
    text: 'text-amber-100',
  },
  rose: {
    border: 'border-rose-300/25',
    bg: 'bg-rose-400/10',
    icon: 'text-rose-100',
    text: 'text-rose-100',
  },
  slate: {
    border: 'border-white/10',
    bg: 'bg-white/[0.04]',
    icon: 'text-gray-200',
    text: 'text-gray-100',
  },
}

const navItems: NavItem[] = [
  { id: 'start', label: 'Быстрый старт', icon: CheckCircle2 },
  { id: 'logic', label: 'Логика CRM', icon: ClipboardList },
  { id: 'roles', label: 'Роли и доступы', icon: ShieldCheck },
  { id: 'workspace', label: 'Рабочее место', icon: MessageSquareText },
  { id: 'bots-leads', label: 'Боты и лиды', icon: Bot },
  { id: 'funnels', label: 'Воронки', icon: Workflow },
  { id: 'broadcasts', label: 'Рассылки', icon: Megaphone },
  { id: 'tracking', label: 'Трекинг и баеры', icon: MousePointerClick },
  { id: 'settings', label: 'Настройки', icon: Settings },
  { id: 'integrations', label: 'Интеграции', icon: Plug },
  { id: 'domains', label: 'Ленды и домены', icon: Globe2 },
  { id: 'metrics', label: 'Метрики', icon: Calculator },
  { id: 'ops', label: 'Эксплуатация', icon: Server },
]

const quickStartSteps = [
  'Создайте проект, задайте SLA красных чатов, языки оператора и клиента.',
  'Подключите Telegram-бота проекта и проверьте webhook.',
  'Добавьте команду, роли и доступы к нужным проектам.',
  'Настройте статусы лида, теги, партнерские интеграции и Google Sheets.',
  'Создайте tracking-ссылки и, если нужен трафик через ленды, припаркуйте домен.',
  'Соберите воронку: триггер, сообщения, ожидание ответа, условия, CRM-действия.',
  'Опубликуйте воронку, протестируйте путь лида и только потом включайте трафик.',
]

const logicFlows: LogicFlow[] = [
  {
    title: 'Старт бота и подписчик',
    icon: Bot,
    tone: 'cyan',
    steps: [
      'Пользователь открывает deep-link Telegram или пишет /start напрямую.',
      'CRM создает или находит чат и сохраняет входящее сообщение пользователя.',
      'Подписчик/старт в метриках считается только по входящему тексту /start или /start@bot, а не по факту создания чата.',
      'Если у /start есть tracking code, чат связывается с tracking-ссылкой; без кода он попадает в “Без трекинга”.',
    ],
  },
  {
    title: 'Лид и статус лида',
    icon: UsersRound,
    tone: 'emerald',
    steps: [
      'Лид привязан к чату, проекту и текущему статусу из проектного справочника статусов.',
      'Старт бота не равен лиду в трекинге. Лидом для CPL и CR считается только статус, выбранный в Настройки -> Проект -> “Лид в трекинге”.',
      'По умолчанию в tracking-набор входят submitted и qualified; проект может выбрать другой набор статусов.',
      'Дата лида для аналитики берется из текущего цикла чата, а если цикла нет - из даты создания лида.',
    ],
  },
  {
    title: 'Воронка и ручная обработка',
    icon: Workflow,
    tone: 'violet',
    steps: [
      'Активная опубликованная версия воронки обслуживает новых лидов; черновик нужен для безопасной подготовки изменений.',
      'Когда менеджер забирает диалог, сценарий можно поставить на паузу, чтобы бот не продолжал писать поверх ручной обработки.',
      'Менеджер может вернуть человека в воронку на нужный шаг, если сценарий должен продолжиться после ручного контакта.',
      'Блок вопроса или сообщения должен явно ждать ответ, иначе сценарий пойдет дальше сразу после отправки.',
    ],
  },
  {
    title: 'Трекинг, ленды и баеры',
    icon: MousePointerClick,
    tone: 'amber',
    steps: [
      'Tracking-ссылка хранит код, бота, баера, расходную модель, базовый CR и точку входа в воронку.',
      'Ленд подставляет Telegram-ссылку CRM на сервере, чтобы не терять tracking code, UTM и выбранный шаг воронки.',
      'Клики считаются по открытию tracking/ленд-ссылки, старты - по фактическому /start в Telegram, лиды - по выбранным статусам проекта.',
      'Баерская статистика агрегируется по tracking-ссылкам баера: расход, клики, старты, лиды, поданные, CPL и конверсии.',
    ],
  },
  {
    title: 'Партнеры, Google Sheets и бэкапы',
    icon: Plug,
    tone: 'slate',
    steps: [
      'Подача партнеру идет через mapping полей, проверку обязательных данных, postback URL и распознавание ответа партнера.',
      'Google Sheets выгружает лидов при переходе в выбранные trigger statuses проекта.',
      'Валидность лида для качества менеджера появляется только из обратной информации партнера или финального qualified-статуса.',
      'Бэкап базы создается ARQ-задачей через pg_dump в .sql.gz, проверяется полным чтением архива и отправляется в закрытый Telegram-канал.',
    ],
  },
]

const featureCards: FeatureCard[] = [
  {
    title: 'Чаты',
    description: 'Операторская зона: входящие диалоги, перевод, карточка лида и ручная подача в CRM.',
    icon: MessageSquareText,
    tone: 'cyan',
    bullets: [
      'Список чатов фильтруется по проекту, боту, оператору, статусу и поиску.',
      'Лента показывает сообщения клиента, бота и менеджера в хронологии.',
      'Карточка лида хранит контакты, статусы, теги, заметки, историю подач.',
    ],
  },
  {
    title: 'Воронки',
    description: 'Конструктор сценариев Telegram-бота: блоки, ветвления, медиа, ожидание ответа и CRM-действия.',
    icon: Workflow,
    tone: 'violet',
    bullets: [
      'Редактор работает с версиями: черновик, активная версия, публикация.',
      'A/B, условия и кнопки ведут по разным выходам блока.',
      'Блок вопроса должен включать ожидание ответа, если сценарий не должен идти дальше сразу.',
    ],
  },
  {
    title: 'Боты',
    description: 'Подключение Telegram-ботов, webhook, профиль Telegram и аудит настроек.',
    icon: Bot,
    tone: 'emerald',
    bullets: [
      'Бот создается по Telegram token и привязывается к выбранному проекту.',
      'Webhook можно зарегистрировать повторно после смены домена или токена.',
      'Профиль Telegram синхронизирует имя, about, description и аватар.',
    ],
  },
  {
    title: 'Лиды',
    description: 'Единый список лидов с фильтрами, тегами, корзиной, переходом в чат и подачей партнеру.',
    icon: UsersRound,
    tone: 'amber',
    bullets: [
      'Фильтры работают по статусу, тегу, партнеру, возрасту, стране, датам и поиску.',
      'Карточка показывает контакты, менеджера, tracking, качество лида и дубли.',
      'Лида можно открыть в чате, подать в CRM партнера или перенести в корзину.',
    ],
  },
  {
    title: 'Рассылки',
    description: 'Массовая отправка сообщений по сегментам с расписанием, медиа и отчетом доставки.',
    icon: Megaphone,
    tone: 'emerald',
    bullets: [
      'Аудитория собирается include/exclude правилами и предпросмотром.',
      'Контент поддерживает цепочку сообщений, задержки, кнопки и медиа.',
      'Отчет показывает отправлено, доставлено, прочитано, ответы и ошибки.',
    ],
  },
  {
    title: 'Трекинг',
    description: 'Tracking-ссылки, расходы, клики, старты, лиды, CPL и оценка качества трафика.',
    icon: MousePointerClick,
    tone: 'amber',
    bullets: [
      'Код ссылки привязывает чат и лида к источнику трафика.',
      'Расход можно вносить вручную или через баер-бота.',
      'Конверсионный статус сравнивает фактический CR с базовым CR ссылки.',
    ],
  },
  {
    title: 'Аналитика',
    description: 'Сводки по проекту, баерам, ссылкам, расходам, конверсиям и просадкам воронки.',
    icon: BarChart3,
    tone: 'cyan',
    bullets: [
      'Показывает расходы, клики, лиды, поданные лиды и стоимость результата.',
      'Помогает сравнивать баеров и отслеживать слабые этапы воронки.',
      'Формулы расчета вынесены в отдельный раздел ниже.',
    ],
  },
  {
    title: 'Настройки',
    description: 'Проект, команда, баеры, статусы, теги, партнеры, Google Sheets, домены и перевод.',
    icon: Settings,
    tone: 'slate',
    bullets: [
      'Admin и Super Admin управляют проектными настройками.',
      'Пользователь может иметь доступ сразу к нескольким проектам.',
      'DeepL, Google и LibreTranslate настраиваются на уровне системных ключей.',
    ],
  },
  {
    title: 'Бэкапы',
    description: 'Резервные копии PostgreSQL через pg_dump, проверка gzip/SQL и доставка в Telegram.',
    icon: Database,
    tone: 'rose',
    bullets: [
      'Файл создается в custom dump формате, сжатым и готовым к восстановлению.',
      'Опциональное шифрование включается через BACKUP_ENCRYPTION_KEY.',
      'Telegram-отправка ограничена BACKUP_TELEGRAM_MAX_UPLOAD_MB.',
    ],
  },
]

const roleRows: Array<[string, string]> = [
  ['Super Admin', 'Все проекты, архивирование проектов, команда, интеграции, баеры, настройки, аналитика и эта документация.'],
  ['Admin', 'Управление доступными проектами, командой проекта, интеграциями, баерами и настройками.'],
  ['Manager', 'Операционная работа с чатами и лидами, подача лидов партнеру, шаблоны сообщений и выбор активной воронки без доступа к редактированию конструктора.'],
  ['Operator', 'Работа с диалогами, ответ клиентам, базовые действия с лидом в пределах доступа.'],
]

const funnelBlocks: Array<[string, string]> = [
  ['Старт / Триггер', 'Запускает сценарий: новый чат, команда /start или ручной запуск.'],
  ['Сообщение', 'Отправляет текст, кнопки, фото, видео, voice, video note или документ. Может ждать ответ.'],
  ['Вопрос / сбор данных', 'Валидирует ответ, сохраняет поле лида и управляет таймаутом/повторами.'],
  ['Условие', 'Проверяет ответ, поле лида, тег, статус, tracking link, Hold-режим или назначение оператора.'],
  ['Hold: сегодня/завтра', 'Ведет лида в ветку сегодня или завтра и может выставлять время созвона.'],
  ['A/B тест', 'Делит трафик по вариантам. Сумма весов должна быть 100%, иначе статистика становится нечитаемой.'],
  ['CRM-действие', 'Добавляет/удаляет теги, меняет статус, пишет поле, назначает оператора, добавляет заметку, подает партнеру.'],
  ['Таймер / ожидание', 'Ждет заданное время или обрабатывает таймаут ожидания ответа.'],
  ['Оператор', 'Передает чат менеджеру или возвращает управление боту.'],
  ['Интеграция', 'Выполняет webhook/HTTP-запрос из сценария.'],
  ['Завершение', 'Останавливает сценарий или завершает его с итоговым статусом.'],
]

const settingsRows: Array<[string, string]> = [
  ['Проект', 'Название, SLA красных чатов, язык оператора, язык клиента по умолчанию, включение перевода.'],
  ['Команда', 'Создание пользователей, смена ролей, паролей и матрица доступа к проектам.'],
  ['Баеры', 'Пользователи-баеры, инвайты, Telegram ID, привязка к баер-боту и удаление из CRM.'],
  ['Статусы', 'Коды и названия этапов лида. Базовые: new, in_progress, submitted, applied, qualified, lost.'],
  ['Теги', 'Проектные метки для фильтрации, сегментации рассылок и условий воронки.'],
  ['Партнеры', 'Postback URL, авторизация, mapping полей, обязательные поля, retry и распознавание ответа.'],
  ['Google Таблицы', 'Spreadsheet ID, лист, активность интеграции и статусы-триггеры экспорта.'],
  ['Лендинги и Домены', 'Парковка доменов, DNS-памятка, лендинги с ref/UTM и загрузка кастомного HTML.'],
]

const botLeadRows: Array<[string, string]> = [
  ['Создание бота', 'Откройте Боты, выберите проект, вставьте Telegram token. CRM подтянет identity из Telegram и зарегистрирует webhook.'],
  ['Webhook', 'Используйте повторную регистрацию webhook после смены публичного домена, токена или Telegram webhook secret.'],
  ['Профиль Telegram', 'Можно обновить CRM-название, about, description и аватарку. Изменения синхронизируются с Telegram.'],
  ['Аудит бота', 'CSV лог настроек помогает проверить, кто и когда менял профиль, webhook или токен.'],
  ['Список лидов', 'Лиды показываются по выбранному проекту и выбранным ботам; можно фильтровать активных и корзину.'],
  ['Фильтры лидов', 'Доступны статус, тег, партнер, возраст, страна, даты, поиск по контакту и Telegram-данным.'],
  ['Карточка лида', 'Показывает телефон, время созвона, дату создания, менеджера, страну, tracking, score, Chat ID и Telegram ID.'],
  ['Действия с лидом', 'Открыть чат, подать в CRM партнера, переместить в корзину или восстановить из корзины.'],
]

const formulaGroups: Array<{ title: string; formulas: Formula[] }> = [
  {
    title: 'Верхняя панель проекта за сегодня',
    formulas: [
      {
        label: 'Лиды сегодня',
        value: 'count(distinct Lead.id)',
        note: 'Считаются только неудаленные лиды проекта, чей текущий статус входит в Настройки -> Проект -> “Лид в трекинге”. Дата берется из текущего цикла чата или даты создания лида.',
      },
      {
        label: 'Подписчики / старты сегодня',
        value: 'count(distinct Chat.id with /start)',
        note: 'Уникальные неудаленные чаты проекта, где за день было входящее текстовое сообщение /start или /start@bot. Создание чата без /start не увеличивает показатель.',
      },
      {
        label: 'Подано сегодня',
        value: 'count(distinct LeadSubmission.lead_id)',
        note: 'Только успешные/завершенные подачи со статусом success или completed.',
      },
      {
        label: 'CR в лид',
        value: 'leads_today / subscribers_today * 100',
        note: 'Конверсия из фактических Telegram-стартов в лиды по выбранным tracking-статусам. Если стартов нет, значение равно 0.',
      },
      {
        label: 'Стоимость лида',
        value: 'spend_today / leads_today',
        note: 'Расход берется из TrackingSpend за текущую дату. При нуле лидов возвращается $0.00.',
      },
      {
        label: 'Стоимость поданного',
        value: 'spend_today / submitted_today',
        note: 'Показывает цену успешной подачи. При нуле подач возвращается $0.00.',
      },
    ],
  },
  {
    title: 'Трекинг и аналитика ссылок',
    formulas: [
      {
        label: 'CR в лид',
        value: 'leads / starts * 100',
        note: 'starts - это уникальные Telegram /start за период. leads считаются только по статусам, выбранным в Настройки -> Проект -> Лид в трекинге. В оценке качества ссылки sample = clicks, а если кликов нет, то starts.',
      },
      {
        label: 'CR в подачу',
        value: 'submitted_leads / leads * 100',
        note: 'Submitted набор включает submitted, applied и qualified.',
      },
      {
        label: 'CR в депозит',
        value: 'deposits / submitted_leads * 100',
        note: 'Депозитами считаются финальные квалифицированные события, если они заведены в статусах/метриках.',
      },
      {
        label: 'CPL',
        value: 'spend / leads',
        note: 'Стоимость лида по выбранной ссылке, баеру, проекту или периоду. Лид берется из проектного набора tracking-статусов, а не из факта старта.',
      },
      {
        label: 'CPSL',
        value: 'spend / submitted_leads',
        note: 'Стоимость поданного лида.',
      },
      {
        label: 'CPD',
        value: 'spend / deposits',
        note: 'Стоимость депозита. Все денежные значения округляются до 2 знаков.',
      },
      {
        label: 'Статус CR',
        value: 'fact_cr vs base_conversion_rate',
        note: 'high_cr >= 120% от базы, low_cr <= 70% от базы, normal_cr между ними, insufficient_data если sample меньше min_sample_size.',
      },
      {
        label: 'Без трекинга',
        value: 'project_total - sum(tracking_links)',
        note: 'Отдельная карточка показывает прямые старты и лиды без tracking_link_id. Это помогает увидеть трафик, пришедший без рекламной ссылки или без кода.',
      },
    ],
  },
  {
    title: 'Баеры',
    formulas: [
      {
        label: 'Расход баера',
        value: 'sum(TrackingSpend.amount)',
        note: 'Сумма расходов по tracking-ссылкам, привязанным к баеру.',
      },
      {
        label: 'Лиды баера',
        value: 'count(distinct Lead.id)',
        note: 'Лиды считаются через чат и tracking-link баера только по статусам проекта из настройки “Лид в трекинге”; удаленные/reset чаты исключаются.',
      },
      {
        label: 'Конверсия в лид',
        value: 'leads / clicks * 100',
        note: 'Если кликов нет, возвращается 0.',
      },
      {
        label: 'CPL баера',
        value: 'total_spend / leads',
        note: 'Показывает фактическую стоимость лида по баеру.',
      },
      {
        label: 'Конверсия в подачу',
        value: 'submitted_leads / leads * 100',
        note: 'Считает долю лидов баера, дошедших до submitted/applied/qualified.',
      },
    ],
  },
]

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(' ')
}

function Section({
  id,
  title,
  kicker,
  icon: Icon,
  children,
}: {
  id: string
  title: string
  kicker?: string
  icon: LucideIcon
  children: ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-28 rounded-xl border border-white/10 bg-surface/80 shadow-card">
      <div className="border-b border-white/10 px-4 py-4 sm:px-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-cyan-300/25 bg-cyan-400/10 text-cyan-100">
            <Icon size={20} />
          </div>
          <div className="min-w-0">
            {kicker ? (
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/80">{kicker}</p>
            ) : null}
            <h2 className="mt-1 text-xl font-semibold text-white sm:text-2xl">{title}</h2>
          </div>
        </div>
      </div>
      <div className="space-y-5 p-4 sm:p-5">{children}</div>
    </section>
  )
}

function FeatureCardView({ card }: { card: FeatureCard }) {
  const Icon = card.icon
  const tone = toneStyles[card.tone]

  return (
    <article className={cn('rounded-xl border p-4', tone.border, tone.bg)}>
      <div className="flex items-start gap-3">
        <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border', tone.border, tone.bg, tone.icon)}>
          <Icon size={20} />
        </div>
        <div className="min-w-0">
          <h3 className={cn('text-lg font-semibold', tone.text)}>{card.title}</h3>
          <p className="mt-1 text-sm leading-6 text-gray-400">{card.description}</p>
        </div>
      </div>
      <ul className="mt-4 space-y-2 text-sm leading-6 text-gray-300">
        {card.bullets.map((item) => (
          <li key={item} className="flex gap-2">
            <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-300" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </article>
  )
}

function LogicFlowCard({ flow }: { flow: LogicFlow }) {
  const Icon = flow.icon
  const tone = toneStyles[flow.tone]

  return (
    <article className={cn('rounded-xl border p-4', tone.border, tone.bg)}>
      <div className="flex items-start gap-3">
        <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border', tone.border, tone.bg, tone.icon)}>
          <Icon size={20} />
        </div>
        <div className="min-w-0">
          <h3 className={cn('text-base font-semibold', tone.text)}>{flow.title}</h3>
          <ol className="mt-3 space-y-2 text-sm leading-6 text-gray-300">
            {flow.steps.map((step, index) => (
              <li key={step} className="flex gap-2">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-white/10 bg-black/20 text-[11px] font-semibold text-gray-200">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </article>
  )
}

function NumberedList({ items }: { items: string[] }) {
  return (
    <ol className="space-y-3">
      {items.map((item, index) => (
        <li key={item} className="flex gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm leading-6 text-gray-300">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-cyan-400/10 text-sm font-semibold text-cyan-100">
            {index + 1}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  )
}

function PairTable({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/10">
      <div className="divide-y divide-white/10">
        {rows.map(([label, value]) => (
          <div key={label} className="grid gap-2 bg-white/[0.02] p-4 text-sm md:grid-cols-[220px_minmax(0,1fr)]">
            <div className="font-semibold text-white">{label}</div>
            <div className="leading-6 text-gray-400">{value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FormulaTable({ title, formulas }: { title: string; formulas: Formula[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
      <div className="border-b border-white/10 px-4 py-3">
        <h3 className="text-base font-semibold text-white">{title}</h3>
      </div>
      <div className="divide-y divide-white/10">
        {formulas.map((formula) => (
          <div key={formula.label} className="grid gap-3 p-4 text-sm md:grid-cols-[180px_260px_minmax(0,1fr)]">
            <div className="font-semibold text-gray-100">{formula.label}</div>
            <code className="min-w-0 rounded-lg border border-cyan-300/15 bg-cyan-400/10 px-3 py-2 text-[13px] text-cyan-100">
              {formula.value}
            </code>
            <div className="leading-6 text-gray-400">{formula.note}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ScreenMap({
  title,
  description,
  blocks,
}: {
  title: string
  description: string
  blocks: Array<{ label: string; width?: string; tone?: Tone }>
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-[#080c16] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-white">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-gray-500">{description}</p>
        </div>
        <Smartphone className="h-5 w-5 shrink-0 text-cyan-200" />
      </div>
      <div className="flex min-h-44 gap-2 overflow-hidden rounded-xl border border-white/10 bg-background p-2">
        {blocks.map((block) => {
          const tone = toneStyles[block.tone ?? 'slate']
          return (
            <div
              key={block.label}
              className={cn(
                'flex min-w-0 items-center justify-center rounded-lg border px-2 text-center text-xs font-semibold leading-5',
                block.width ?? 'flex-1',
                tone.border,
                tone.bg,
                tone.text,
              )}
            >
              {block.label}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function InfoCallout({
  title,
  children,
  tone = 'cyan',
}: {
  title: string
  children: ReactNode
  tone?: Tone
}) {
  const style = toneStyles[tone]
  return (
    <div className={cn('rounded-xl border p-4', style.border, style.bg)}>
      <div className="flex gap-3">
        <AlertTriangle className={cn('mt-0.5 h-5 w-5 shrink-0', style.icon)} />
        <div>
          <h3 className={cn('font-semibold', style.text)}>{title}</h3>
          <div className="mt-2 text-sm leading-6 text-gray-300">{children}</div>
        </div>
      </div>
    </div>
  )
}

function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-semibold text-gray-200">
      {children}
    </span>
  )
}

export default function DocsPage() {
  return (
    <div className="touch-scroll h-full min-h-0 overflow-y-auto scroll-smooth pr-0 text-gray-200">
      <div className="mx-auto w-full max-w-7xl space-y-5 pb-8">
        <header className="rounded-xl border border-white/10 bg-surface/80 p-4 shadow-card sm:p-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-4xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200">
                <BookOpen size={14} />
                CRM Manual
              </div>
              <h1 className="mt-4 text-3xl font-semibold text-white sm:text-4xl">Документация CRM SFERA</h1>
              <p className="mt-3 text-sm leading-6 text-gray-400 sm:text-base sm:leading-7">
                Полный справочник по рабочим экранам, настройкам, воронкам, рассылкам, трекингу,
                интеграциям, доменам, бэкапам и расчету метрик. Страница сделана внутри CRM, чтобы
                команда могла открыть ее в любой момент без внешних файлов.
              </p>
            </div>
            <div className="grid gap-2 text-sm text-gray-400 sm:grid-cols-3 lg:w-[420px]">
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="text-lg font-semibold text-white">13</div>
                <div>разделов</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="text-lg font-semibold text-white">30+</div>
                <div>операций</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="text-lg font-semibold text-white">100%</div>
                <div>по CRM</div>
              </div>
            </div>
          </div>
        </header>

        <nav className="rounded-xl border border-white/10 bg-surface/80 p-3 shadow-card" aria-label="Навигация по документации">
          <div className="mb-3 flex items-center gap-2 px-1 text-sm font-semibold text-white">
            <Search size={16} className="text-cyan-200" />
            Быстрая навигация
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm font-medium text-gray-300 transition hover:border-cyan-300/40 hover:text-white"
                >
                  <Icon size={16} className="shrink-0 text-cyan-200" />
                  <span className="truncate">{item.label}</span>
                </a>
              )
            })}
          </div>
        </nav>

        <section className="rounded-xl border border-white/10 bg-surface/80 p-4 shadow-card sm:p-5">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/80">Карта CRM</p>
              <h2 className="mt-1 text-xl font-semibold text-white">Основные модули</h2>
            </div>
            <p className="max-w-2xl text-sm leading-6 text-gray-500">
              Это короткая шпаргалка по зонам системы. Подробные инструкции, ограничения и формулы
              находятся в разделах ниже.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {featureCards.map((card) => (
              <FeatureCardView key={card.title} card={card} />
            ))}
          </div>
        </section>

        <Section id="start" title="Быстрый старт" kicker="Порядок настройки" icon={CheckCircle2}>
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
            <NumberedList items={quickStartSteps} />
            <ScreenMap
              title="Как читать CRM"
              description="На десктопе CRM делится на закрепленное меню, верхний выбор проекта/бота и рабочий экран. На телефоне меню и селекторы открываются отдельными слоями."
              blocks={[
                { label: 'Меню', width: 'w-20', tone: 'slate' },
                { label: 'Проект и бот', width: 'flex-[1.1]', tone: 'cyan' },
                { label: 'Рабочая область', width: 'flex-[2]', tone: 'emerald' },
              ]}
            />
          </div>
          <InfoCallout title="Главное правило запуска" tone="amber">
            Не включайте трафик на новую воронку сразу после публикации. Сначала пройдите тестовый
            сценарий с реальным Telegram-ботом, проверьте карточку лида, статус, tracking link,
            партнерскую подачу и экспорт в Google Sheets.
          </InfoCallout>
        </Section>

        <Section id="logic" title="Как работает CRM" kicker="Системная логика" icon={ClipboardList}>
          <p className="text-sm leading-6 text-gray-400">
            Этот раздел описывает цепочку событий без маркетинговых упрощений: что считается стартом,
            когда появляется лид, какие статусы попадают в трекинг, как воронка уступает управление
            менеджеру и откуда берутся цифры в верхней панели, аналитике и tracking-экране.
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            {logicFlows.map((flow) => (
              <LogicFlowCard key={flow.title} flow={flow} />
            ))}
          </div>
          <InfoCallout title="Самое важное про старты и лиды" tone="amber">
            Старт бота и лид в трекинге специально считаются разными событиями. Старт фиксирует факт
            входа пользователя в Telegram-бота, а лид для CPL/CR появляется только после перехода в
            один из статусов, выбранных в настройке проекта “Лид в трекинге”. Поэтому рекламный клик,
            Telegram /start и квалифицированный лид могут иметь разные значения в одной и той же дате.
          </InfoCallout>
        </Section>

        <Section id="roles" title="Роли и доступы" kicker="Команда" icon={ShieldCheck}>
          <p className="text-sm leading-6 text-gray-400">
            Доступы управляются в настройках команды. У пользователя есть роль и список проектов,
            к которым он допущен. Это позволяет выдать, например, администратору доступ к двум
            проектам из трех без раскрытия всей CRM.
          </p>
          <PairTable rows={roleRows} />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 text-base font-semibold text-white">
                <UsersRound size={18} className="text-cyan-200" />
                Как выдать доступ
              </h3>
              <ol className="mt-3 space-y-2 text-sm leading-6 text-gray-400">
                <li>1. Откройте Настройки {'->'} Команда.</li>
                <li>2. Создайте пользователя или отредактируйте существующего.</li>
                <li>3. Выберите роль и отметьте проекты в матрице доступа.</li>
                <li>4. Сохраните. Селектор проекта покажет только доступные проекты.</li>
              </ol>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 text-base font-semibold text-white">
                <KeyRound size={18} className="text-emerald-200" />
                Пароли и безопасность
              </h3>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                Пароль задается при создании пользователя и может быть изменен администратором.
                После увольнения пользователя лучше удалить доступы к проектам и сменить пароль,
                а не оставлять учетку с активными правами.
              </p>
            </div>
          </div>
          <InfoCallout title="Ограничения менеджера" tone="amber">
            Менеджер может вести переписку, забрать чат себе, отправить лида в корзину, подать лида
            партнеру, пользоваться шаблонами и выбрать активную воронку. Блокировка пользователя,
            полный сброс диалога, редактирование конструктора, удаление рассылок из базы, боты,
            трекинг и настройки должны оставаться выше менеджерского уровня.
          </InfoCallout>
        </Section>

        <Section id="workspace" title="Рабочее место оператора" kicker="Чаты, лиды, перевод" icon={MessageSquareText}>
          <div className="grid gap-4 lg:grid-cols-2">
            <ScreenMap
              title="Десктоп: 3 колонки"
              description="Список чатов, лента сообщений и карточка лида видны одновременно."
              blocks={[
                { label: 'Список чатов', width: 'w-28', tone: 'cyan' },
                { label: 'Сообщения + composer', width: 'flex-1', tone: 'emerald' },
                { label: 'Лид', width: 'w-28', tone: 'violet' },
              ]}
            />
            <ScreenMap
              title="Мобильный режим"
              description="Сначала список, после выбора чата открывается лента, карточка лида доступна отдельным drawer."
              blocks={[
                { label: 'Чат', width: 'flex-1', tone: 'emerald' },
                { label: 'Инфо', width: 'w-20', tone: 'violet' },
              ]}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Список чатов</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Используйте поиск по имени, телефону, username и быстрые фильтры: все, мои,
                не отвечено, горячие. Список зависит от выбранного проекта и бота.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Лента сообщений</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Composer отправляет ответ менеджера. Перевод должен быть лаконичным действием:
                менеджер переводит текст, проверяет стиль и только потом отправляет клиенту.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Карточка лида</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Здесь меняются статус, теги, данные лида, назначение менеджера, заметки и подача
                в партнерскую CRM. История подач показывает результат postback.
              </p>
            </div>
          </div>
          <InfoCallout title="Перевод и апрув текста" tone="cyan">
            Для LATAM и похожих рынков машинный перевод нужно проверять вручную: DeepL может ставить
            перевернутые знаки вопроса/восклицания, а это выглядит слишком официально. Правильный
            UX: перевести текст в отдельном поле, отредактировать, затем отправить финальную версию.
          </InfoCallout>
        </Section>

        <Section id="bots-leads" title="Боты и лиды" kicker="Подключение и обработка" icon={Bot}>
          <p className="text-sm leading-6 text-gray-400">
            Эти экраны закрывают техническое подключение Telegram и операционную работу со всеми
            лидами проекта. Сначала подключается бот, затем трафик из воронок, рассылок и лендингов
            начинает создавать чаты и лиды, которые попадают в общий список.
          </p>
          <PairTable rows={botLeadRows} />
          <div className="grid gap-4 md:grid-cols-2">
            <InfoCallout title="Когда нужен экран Боты" tone="emerald">
              При добавлении нового Telegram-бота, замене токена, переносе домена, обновлении профиля
              бота или выгрузке аудита изменений. Если сообщения перестали приходить, первым делом
              проверьте webhook и активный проект.
            </InfoCallout>
            <InfoCallout title="Когда нужен экран Лиды" tone="amber">
              Для массового просмотра лидов, поиска дублей, фильтрации по качеству/статусам, ручной
              подачи партнеру и восстановления из корзины. Для живой переписки удобнее открыть лида
              сразу в чате.
            </InfoCallout>
          </div>
        </Section>

        <Section id="funnels" title="Воронки" kicker="Конструктор сценариев" icon={Workflow}>
          <p className="text-sm leading-6 text-gray-400">
            Воронка состоит из блоков и связей. У каждого блока есть вход, выходы и конфигурация.
            Черновик можно редактировать, активная версия обслуживает реальных лидов. После изменений
            публикуйте новую версию и проверяйте историю версий.
          </p>
          <PairTable rows={funnelBlocks} />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <FileText size={18} className="text-cyan-200" />
                Сообщения и медиа
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Сообщение поддерживает цепочку шагов: текст, caption, delay, кнопки, photo, video,
                voice, video_note и document. Медиа можно загрузить или указать Telegram file_id.
                В карточке шага нужно смотреть имя файла, тип и размер, чтобы понимать, что именно прикреплено.
              </p>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                В тексте работают переменные first_name, username, phone, lead_status, project, bot
                и custom.&lt;ключ&gt;. Контактная inline-кнопка открывает Telegram Mini App с нативным
                запросом номера, сохраняет присланный номер в поле phone, после чего он доступен как
                {'{{phone}}'}. Для кнопки можно выбрать следующий шаг воронки; нужен публичный HTTPS
                BASE_URL.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <Timer size={18} className="text-amber-200" />
                Ожидание ответа
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Если после вопроса нужно ждать клиента, включайте wait_for_answer в вопросе или сообщении.
                Без ожидания сценарий продолжит движение дальше сразу после отправки сообщения.
              </p>
            </div>
          </div>
          <InfoCallout title="A/B веса и связи" tone="amber">
            Вес вариантов A/B должен суммарно давать 100%. Если получилось 120%, распределение
            становится нечитаемым для менеджера и статистики. Разные выходы блока могут вести в
            один и тот же следующий блок, если бизнес-логика специально сходится в одну ветку.
          </InfoCallout>
        </Section>

        <Section id="broadcasts" title="Рассылки" kicker="Сегменты и доставка" icon={Megaphone}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Создание рассылки</h3>
              <ol className="mt-3 space-y-2 text-sm leading-6 text-gray-400">
                <li>1. Выберите проект и бота.</li>
                <li>2. Соберите аудиторию include/exclude правилами.</li>
                <li>3. Проверьте предпросмотр и количество получателей.</li>
                <li>4. Настройте цепочку сообщений, медиа, кнопки и задержки.</li>
                <li>5. Отправьте сразу или запланируйте время.</li>
              </ol>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Статусы и отчет</h3>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                Статусы: draft, scheduled, processing, paused, completed, cancelled.
                Отчет показывает total_recipients, sent_count, failed_count, pending, skipped,
                error_examples, а аналитика доставки дополнительно показывает delivered, read и replied.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill>photo</Pill>
            <Pill>video</Pill>
            <Pill>voice</Pill>
            <Pill>video_note</Pill>
            <Pill>document</Pill>
            <Pill>buttons</Pill>
            <Pill>delay_seconds</Pill>
            <Pill>stop_on_reply</Pill>
          </div>
        </Section>

        <Section id="tracking" title="Трекинг, баеры и баер-бот" kicker="Источники трафика" icon={MousePointerClick}>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Tracking-ссылка</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Хранит title, code, buyer_name, ad_type, payment_type, invite_link, base_conversion_rate
                и min_sample_size. Код нужен, чтобы Telegram /start связал чат с источником.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Расход</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Расходы пишутся в TrackingSpend: дата, сумма, валюта, комментарий и source.
                Источники: crm_manual и buyer_bot.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Баер-бот</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Баер получает инвайт, привязывает Telegram ID, отправляет расходы и смотрит
                статистику или график за 7/30 дней. В разделе Facebook Pixel он задает Pixel ID и
                CAPI token: замена обновляет все его старые ссылки, а новые наследуют эти данные.
              </p>
            </div>
          </div>
          <InfoCallout title="Вход через Telegram" tone="cyan">
            Вход в веб-CRM подтверждается через админ-бота, а не через баер-бота. Укажите Telegram
            ID в аккаунте сотрудника и настройте токен админ-бота в системных настройках. Настройка
            домена Telegram Login Widget для этого сценария не требуется.
          </InfoCallout>
          <InfoCallout title="Как читать качество ссылки" tone="cyan">
            Если sample меньше min_sample_size, ссылка помечается как insufficient_data. При достаточной
            выборке CR сравнивается с base_conversion_rate: выше 120% от базы - high_cr, ниже 70% -
            low_cr, между ними - normal_cr.
          </InfoCallout>
        </Section>

        <Section id="settings" title="Все настройки CRM" kicker="Что за что отвечает" icon={Settings}>
          <PairTable rows={settingsRows} />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <Tags size={18} className="text-emerald-200" />
                Статусы лида
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Статус определяет этап обработки и участвует в фильтрах, рассылках, Google Sheets,
                метриках submitted и финальных исходах. Терминальные статусы: qualified и lost.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <Languages size={18} className="text-cyan-200" />
                Языки проекта
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Язык оператора задает язык менеджера, язык клиента по умолчанию используется, когда
                по чату нельзя надежно определить язык. Перевод включается отдельно.
              </p>
            </div>
          </div>
        </Section>

        <Section id="integrations" title="Интеграции" kicker="Google Sheets, партнеры, перевод" icon={Plug}>
          <div className="grid gap-4 lg:grid-cols-3">
            <article className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <Table className="h-6 w-6 text-emerald-200" />
              <h3 className="mt-3 font-semibold text-white">Google Sheets</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Укажите Spreadsheet ID, имя листа и статусы-триггеры. Сервисный аккаунт задается
                переменной GOOGLE_SERVICE_ACCOUNT_JSON, а email отображается в интерфейсе. Таблицу
                нужно расшарить на этот email с правами Editor.
              </p>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                Экспортируемые колонки: дата, имя, телефон, Telegram, страна, возраст, ссылка, баер,
                статус, CPL и score confidence.
              </p>
            </article>
            <article className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <Send className="h-6 w-6 text-cyan-200" />
              <h3 className="mt-3 font-semibold text-white">Партнерская CRM</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Настраиваются URL, HTTP-метод, JSON/Form, авторизация, заголовки, query-параметры,
                обязательные поля, разбор ответа и повторы. Простой mapping сохранен для плоских API,
                а JSON-шаблон собирает вложенное тело без отдельной разработки под партнера.
              </p>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                Успех по умолчанию распознается как success, accepted или ok. Дубликат - duplicate.
                Ошибка - rejected или error.
              </p>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                В шаблоне доступны lead, custom, tracking, buyer, project и bot. Секреты вызываются
                через secret.KEY, пароль и IP из настроенного CIDR-пула - через random.password и random.ipv4.
                Комментарий менеджера доступен как lead.manager_comment и отправляется только если он
                явно добавлен в mapping или JSON-шаблон. Секретные значения не возвращаются в браузер
                и скрываются в preview.
              </p>
            </article>
            <article className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <Languages className="h-6 w-6 text-violet-200" />
              <h3 className="mt-3 font-semibold text-white">Перевод</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Поддерживаются deepl, google и libretranslate. DeepL отправляется header-based:
                Authorization: DeepL-Auth-Key. Free ключи с :fx автоматически идут на api-free.deepl.com,
                обычные - на api.deepl.com.
              </p>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                Если провайдер не настроен или недоступен, безопасный режим возвращает оригинальный текст,
                а ручной перевод должен показывать ошибку менеджеру.
              </p>
            </article>
          </div>
          <InfoCallout title="Как указать сервисный аккаунт Google" tone="emerald">
            На сервере добавьте полный JSON сервисного аккаунта в GOOGLE_SERVICE_ACCOUNT_JSON.
            В интерфейсе Google Sheets появится service_account_email. Именно этот email добавьте
            в Google Таблицу как Editor. Spreadsheet ID находится в URL между /d/ и /edit.
          </InfoCallout>
        </Section>

        <Section id="domains" title="Лендинги, домены и техдомен" kicker="Трафик и DNS" icon={Globe2}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">Как работает домен</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Простая tracking link продолжает вести прямо в Telegram. Facebook-кампания создаёт
                такую же отдельную tracking link, но встраивает её start-ссылку в лендинг. Поэтому код,
                бот, баер, UTM и выбранный шаг воронки учитываются одинаково в обоих сценариях.
                Техдомен можно использовать напрямую: <code>https://lp.sfera.cyou/l/slug</code>.
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="font-semibold text-white">DNS-подключение</h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                В Bunny DNS можно поставить A-запись на IP origin-сервера и включить CDN Acceleration.
                Альтернатива: добавить рекламный домен в Hostnames общей Pull Zone, включить для него
                SSL и направить CNAME на hostname этой зоны <code>*.b-cdn.net</code>. В таком варианте
                CDN Acceleration у DNS-записи должен быть выключен, поскольку CNAME уже ведёт в CDN.
                Origin Pull Zone должен вести напрямую на сервер по HTTP, сохранять исходный Host и
                не указывать на <code>lp.sfera.cyou</code>, рекламный домен или другую Bunny-зону.
                Для корневого домена используйте CNAME flattening. HTML путей <code>/l/*</code> нельзя
                кэшировать, иначе посетители могут получить чужой start-key или UTM.
              </p>
            </div>
          </div>
          <InfoCallout title="Создание Facebook-кампании" tone="cyan">
            Откройте Настройки → Лендинги и Домены → Создать лендинг → Новая кампания. Выберите бота,
            домен, название, баера и точку входа, затем укажите Pixel / Dataset ID и CAPI access token.
            Proxy и Test event code необязательны. Токен и proxy хранятся на сервере и не возвращаются
            в API или интерфейс. Автопереход можно отключить, если человек должен нажать кнопку сам.
            UTM из рекламного URL имеют приоритет, а значения UTM в форме заполняют только пропуски.
          </InfoCallout>
          <InfoCallout title="Карта событий Pixel и CAPI" tone="emerald">
            <code>page_view</code> и <code>telegram_click</code> отправляются браузерным Pixel.
            <code>bot_start</code> и <code>contact</code> отправляются серверным CAPI автоматически.
            <code>registration</code>, подписка, отписка, sale, resale и приглашение контакта вызываются
            CRM-действием воронки, переходом в статус или добавлением тега. Общую для проекта реакцию
            на тег задавайте в Настройки → Проект → Facebook-события по тегам; она применяется ко всем
            Facebook-кампаниям проекта. Для каждого источника в кампании можно включить событие и
            заменить его на стандартное или custom Meta event. У Purchase доступны value и currency;
            по умолчанию value берётся из <code>{'{{lead.expected_start_amount}}'}</code>. CAPI
            выполняется через ARQ и не задерживает Telegram-воронку.
          </InfoCallout>
          <InfoCallout title="Атрибуция и дедупликация" tone="slate">
            Перед переходом в Telegram лендинг синхронизирует fbp, fbc, IP, User-Agent и URL источника
            с временным start-key в Redis. После /start данные сохраняются у лида и используются CAPI.
            Телефон, email, имя и external_id перед отправкой нормализуются и SHA256-хэшируются.
            CRM формирует стабильный event_id, поэтому повтор задачи воркера не создаёт второй ивент.
          </InfoCallout>
          <InfoCallout title="Контракт кастомного лендинга" tone="amber">
            В ZIP обязателен index.html в корне и хотя бы одна кнопка <code>&lt;a data-crm-telegram-link href=&quot;#&quot;&gt;...&lt;/a&gt;</code>.
            CRM на лету заменяет ее href на deep-link конкретной кампании с кодом и UTM. Не вставляйте
            вручную адрес бота и не делайте самостоятельный redirect в Telegram. Ссылки на старый
            домен t.me и новый telegram.me для текущего бота поддерживаются для обратной совместимости,
            но новый контракт должен использовать data-атрибут. CRM генерирует внешние переходы через
            telegram.me, сохраняя username и start-параметр без изменений.
          </InfoCallout>
          <InfoCallout title="Meta-события кастомного лендинга" tone="emerald">
            Для новой карты используйте <code>data-crm-fb-source=&quot;telegram_click&quot;</code> или вызов
            <code>window.__crmTrackFacebookSource(&quot;registration&quot;)</code>. Старые ZIP с
            <code>data-crm-meta-event</code> и <code>window.__crmTrackMetaEvent(...)</code> продолжают
            работать. Не отправляйте регистрацию на обычный клик, если регистрация подтверждается уже
            внутри Telegram.
          </InfoCallout>
          <InfoCallout title="Кампания из баер-бота" tone="cyan">
            Баер сначала задаёт Pixel ID и CAPI token командой /pixel, затем запускает /fb_campaign.
            Бот предлагает проект, конкретного Telegram-бота, название, техдомен или рекламный домен и
            автопереход. В ответ баер получает URL лендинга, а CRM создаёт связанную tracking link с
            базовой картой событий. Замена Pixel в баер-боте обновляет уже созданные FB-ссылки этого
            баера и применяется к новым.
          </InfoCallout>
          <InfoCallout title="Нагрузка от 5000 открытий в час" tone="amber">
            5000 открытий в час - это примерно 1.4 запроса в секунду до учета статики и пиков.
            Для простого редиректа нагрузка небольшая. Для кастомного HTML с тяжелыми картинками
            нагрузку дают изображения, JS и отсутствие CDN/cache. Практично держать статику легкой,
            включить gzip/brotli и отдавать тяжелые ассеты через CDN.
          </InfoCallout>
        </Section>

        <Section id="metrics" title="Метрики и формулы" kicker="Как считаются цифры" icon={Calculator}>
          <div className="space-y-4">
            {formulaGroups.map((group) => (
              <FormulaTable key={group.title} title={group.title} formulas={group.formulas} />
            ))}
          </div>
          <InfoCallout title="Округление и нули" tone="slate">
            Денежные и процентные значения округляются до 2 знаков, где это требуется аналитикой.
            Если denominator равен нулю, CRM возвращает 0 вместо ошибки деления.
          </InfoCallout>
          <InfoCallout title="Качество лида и горячие чаты" tone="cyan">
            Уверенность лида начинается со 100%. Отсутствие tracking link снижает её на 20 пунктов,
            невалидный телефон - на 25, вероятный дубль - на 40. Уровни: high 80-100, medium 50-79,
            low 0-49. Автоподача включается отдельно для каждого партнёра, учитывает заданный минимальный
            score и никогда не отправляет low-лидов. Это не подтверждение партнёра: валидность в статистике
            менеджера появляется только после обратной информации партнёра. «Горячий» - отдельный сигнал
            вовлечённости: score от 70 либо сильная комбинация контакта, карты, времени связи и профиля.
            Просрочка ответа по SLA показывается отдельной красной меткой и не делает лид горячим.
          </InfoCallout>
        </Section>

        <Section id="ops" title="Эксплуатация и бэкапы" kicker="Сервер и безопасность" icon={Server}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <Database size={18} className="text-rose-200" />
                Резервное копирование
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Бэкап PostgreSQL создается через pg_dump --format=custom --compress=9 --no-owner
                --no-privileges. После создания CRM полностью читает gzip и проверяет SQL-заголовок. При
                BACKUP_ENCRYPTION_KEY файл шифруется AES-256-CBC с PBKDF2.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Pill>is_tg_backup_enabled</Pill>
                <Pill>ARQ 03:00 UTC</Pill>
                <Pill>BACKUP_RETENTION_COUNT</Pill>
                <Pill>BACKUP_RETENTION_DAYS</Pill>
                <Pill>BACKUP_VERIFY</Pill>
              </div>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <h3 className="flex items-center gap-2 font-semibold text-white">
                <Bot size={18} className="text-cyan-200" />
                Telegram-доставка бэкапов
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-400">
                Чтобы выгружать файл в закрытый чат, задайте BACKUP_TELEGRAM_BOT_TOKEN и
                BACKUP_TELEGRAM_CHAT_ID. По умолчанию лимит файла управляется
                BACKUP_TELEGRAM_MAX_UPLOAD_MB и в примере равен 49 MB. Если файл больше, CRM
                отправит уведомление, но не загрузит документ.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Pill>BACKUP_TELEGRAM_BOT_TOKEN</Pill>
                <Pill>BACKUP_TELEGRAM_CHAT_ID</Pill>
                <Pill>BACKUP_TELEGRAM_MAX_UPLOAD_MB</Pill>
              </div>
              <p className="mt-3 text-sm leading-6 text-gray-400">
                Super Admin может из системных настроек отправить в тот же канал диагностические
                логи API и workers за последние 30 минут. Файлы ротируются по размеру, секреты
                маскируются, экспорт ограничен 2 МБ и одним запуском в минуту.
              </p>
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h3 className="flex items-center gap-2 font-semibold text-white">
              <ClipboardList size={18} className="text-emerald-200" />
              Чеклист перед обновлением кода или переносом сервера
            </h3>
            <ol className="mt-3 grid gap-2 text-sm leading-6 text-gray-400 md:grid-cols-2">
              <li className="flex gap-2"><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-cyan-200" />Создать ручной бэкап и проверить sha256.</li>
              <li className="flex gap-2"><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-cyan-200" />Проверить, что gzip-архив и SQL-заголовок валидны.</li>
              <li className="flex gap-2"><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-cyan-200" />Сохранить .env, GOOGLE_SERVICE_ACCOUNT_JSON, токены ботов и BACKUP_ENCRYPTION_KEY.</li>
              <li className="flex gap-2"><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-cyan-200" />На новом сервере восстановить БД через psql.</li>
              <li className="flex gap-2"><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-cyan-200" />Перепроверить webhook Telegram-ботов и DNS доменов.</li>
              <li className="flex gap-2"><ArrowRight className="mt-1 h-4 w-4 shrink-0 text-cyan-200" />Открыть CRM, проверить проекты, чаты, воронки, tracking и интеграции.</li>
            </ol>
          </div>
        </Section>
      </div>
    </div>
  )
}
