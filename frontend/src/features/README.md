# Frontend Feature Rules

Feature-модули — основной формат для новых крупных доменов фронтенда.

- Feature-модуль содержит публичные файлы `api.ts`, `types.ts`, `hooks.ts` и папку `components/`.
- Страницы должны импортировать публичный API feature-модуля, а не его внутренние детали.
- Один feature не должен импортировать внутренние файлы другого feature напрямую.
- Общие UI-компоненты находятся в `frontend/src/shared/ui`.
- Общие API-клиенты находятся в `frontend/src/shared/api`.
- Общие типы находятся в `frontend/src/shared/types`.
- Бизнес-логика не должна жить внутри больших page-компонентов.

## Project/Bot Frontend Scope

- `selectedProjectId` обязателен для новых экранов, которые работают с project-scoped данными.
- `selectedBotIds = []` означает "все боты выбранного проекта".
- Старые страницы пока могут не использовать Project/Bot scope, чтобы не менять текущее поведение.
- Новые features должны читать scope через `ProjectBotSelectionProvider` / `useProjectBotSelection`.
- ProjectSelector и BotSelector живут в общем layout/header, а не внутри отдельных страниц.
- Локальные bot selectors запрещены, если они не являются дополнительным фильтром и явно не синхронизированы с global scope.
- `super_admin` видит все проекты; `admin`, `manager` и `operator` работают в рамках доступного проекта.
- `manager` и `operator` не должны видеть actions управления сотрудниками или проектами.
- Create Project в header доступен только пользователю с ролью `super_admin`; после создания новый проект становится `selectedProjectId`, а `selectedBotIds` сбрасывается в `[]`.
- Create Project modal рендерится как viewport-level dialog через shared `Modal`, а не как header-bound dropdown.

## Tracking Frontend

- Tracking page читает `selectedProjectId` из global Project/Bot selection context.
- `selectedBotIds = []` означает все боты выбранного проекта.
- Несколько выбранных ботов пока показывают project-level metrics без индивидуальной агрегации.
- Project summary берется из `/api/v1/tracking/metrics/project`.
- Link detail берется из `/api/v1/tracking/metrics/links/{link_id}`.
- Manual spend создается и редактируется через tracking spends API.

## Navigation IA

- Sidebar order: `Чаты`, `Воронки`, `Рассылки`, `Боты`, `Лиды`, `Трекинг`, `Аналитика`, `Настройки`.
- `/dashboard` остаётся для совместимости, но основной пункт меню ведёт на `/analytics`.
- `/funnels` — production v1 Funnel Builder. `/broadcasts` остаётся placeholder route до реализации workflow.

## Chats Layout And LeadSidebar Scroll

- `MainLayout` держит viewport через `h-screen` и запрещает body scroll; страницы внутри должны сами задавать scroll-контейнеры.
- `ChatsPage` использует `h-full min-h-0 overflow-hidden` на grid-колонках.
- `ChatList`, message list и `LeadSidebar` скроллятся независимо через внутренние `overflow-y-auto`.
- `LeadSidebar` всегда должен получать bounded parent height: на desktop это правая grid-колонка, на mobile — wrapper внутри shared `Modal`.
- Для flex/grid детей, которые должны скроллиться, обязательны `min-h-0` и явный `h-full` на промежуточных контейнерах.
- Toast viewport не должен иметь z-index выше modal/dialog layers и не должен создавать scroll на body.

## Funnel Builder Frontend

- `frontend/src/pages/FunnelsPage.tsx` отвечает только за route-level orchestration и global project/bot scope.
- Feature код живёт в `frontend/src/features/funnels`: `api.ts`, `types.ts`, `hooks.ts`, `blockCatalog.ts`, `components/`.
- Canvas, settings panels, copy modal, publish review, push rules и field mappings остаются отдельными компонентами.
- Add Block menu показывает универсальные блоки, а не каждый backend `block_type`.
- Specific/legacy `block_type` — внутренняя совместимость и настройка поведения, не primary-level действие в меню.
- Canvas interactions: pan по пустому полю, zoom через controls, drag nodes, соединение через output/input handles.
- Keyboard shortcuts: Delete/Backspace удаляет выбранный блок/связь; Cmd/Ctrl+S сохраняет draft; Esc снимает выбор.
- Связи редактируются через выбранную линию; полный список связей находится в advanced/debug секции.
- `selectedBotIds = []` показывает все funnels проекта, но создание новой funnel требует конкретный bot.
- Если выбран ровно один bot, форма создания preselects его автоматически.
- Copy может переключить global project/bot scope, потому что копия может быть создана в другом проекте.
- У одного bot может быть только одна active published funnel; cards/list показывают active funnel и предупреждают о нескольких funnels на bot.

## Leads Feature

- `frontend/src/features/leads` содержит `api.ts`, `types.ts`, `hooks.ts`, `components/`.
- Leads page читает `selectedProjectId` и `selectedBotIds` из общего scope.
- `Отправить` вызывает backend status-заглушку без внешнего CRM API.
- `Удалить` означает reject/archive, не physical delete.

## Chat Reset UI

- Reset запускается из chat detail через confirm dialog.
- После успешного reset чат убирается из активного списка без full reload.
- Новый входящий Telegram message запускает новый lifecycle на backend.

## Tracking Creation Rule

- Создание tracking links живёт только в `Трекинг`.
- `BotsPage` управляет ботами и webhook, но не создаёт tracking links напрямую.

## Responsive Rules

- Sidebar collapsible на desktop и drawer/offcanvas на tablet/mobile.
- Body-level horizontal overflow запрещён; таблицы скроллятся только внутри контейнеров.
- Новые feature pages должны иметь одно-колоночный mobile layout и не рассчитывать на wide viewport.
