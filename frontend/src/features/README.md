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
