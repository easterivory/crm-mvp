from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()


@router.get("/telegram/contact-request", response_class=HTMLResponse, include_in_schema=False)
async def telegram_contact_request() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>Поделиться номером</title>
  <script src="https://telegram.org/js/telegram-web-app.js?62"></script>
  <style>
    :root { color-scheme: light dark; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 20px;
      box-sizing: border-box; background: var(--tg-theme-bg-color, #0d1222);
      color: var(--tg-theme-text-color, #f3f4f6); font: 16px/1.45 system-ui, sans-serif; }
    main { width: min(100%, 360px); text-align: center; }
    h1 { margin: 0 0 10px; font-size: 22px; }
    p { margin: 0 0 18px; color: var(--tg-theme-hint-color, #9ca3af); }
    button { width: 100%; min-height: 48px; border: 0; border-radius: 8px; padding: 12px 16px;
      background: var(--tg-theme-button-color, #22c55e);
      color: var(--tg-theme-button-text-color, #07120b); font: inherit; font-weight: 700; }
  </style>
</head>
<body>
  <main>
    <h1>Поделиться номером</h1>
    <p id="status">Подтвердите отправку номера в Telegram.</p>
    <button id="request" type="button">Отправить мой номер</button>
  </main>
  <script>
    const app = window.Telegram && window.Telegram.WebApp;
    const status = document.getElementById('status');
    const button = document.getElementById('request');
    let requesting = false;

    function requestContact() {
      if (requesting) return;
      if (!app || typeof app.requestContact !== 'function') {
        status.textContent = 'Обновите Telegram, чтобы поделиться номером.';
        return;
      }
      requesting = true;
      button.disabled = true;
      app.requestContact((shared) => {
        requesting = false;
        button.disabled = false;
        if (shared) {
          status.textContent = 'Номер отправлен.';
          window.setTimeout(() => app.close(), 500);
        } else {
          status.textContent = 'Отправка отменена. Нажмите кнопку, чтобы попробовать снова.';
        }
      });
    }

    if (app) {
      app.ready();
      app.expand();
      window.setTimeout(requestContact, 150);
    }
    button.addEventListener('click', requestContact);
  </script>
</body>
</html>"""
    )
