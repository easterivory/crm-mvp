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
- ProjectSelector и BotSelector живут в общем layout, а не внутри отдельных страниц.
