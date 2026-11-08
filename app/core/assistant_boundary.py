"""Origin restrictions for assistant UI; does not alter legacy CRM CORS behavior."""
from starlette.responses import JSONResponse
from urllib.parse import urlsplit
from app.core.config import settings


class AssistantBoundaryMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/v1/assistant/") or path.startswith("/api/v1/assistant/tools/") or path in {"/api/v1/assistant/session", "/api/v1/assistant/tool-schemas"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        base = urlsplit(settings.BASE_URL)
        if origin and origin != f"{base.scheme}://{base.netloc}":
            return await JSONResponse({"detail": "interactive_approval_required"}, 403)(scope, receive, send)
        async def protected_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if not k.lower().startswith(b"access-control-")]
            await send(message)
        await self.app(scope, receive, protected_send)
