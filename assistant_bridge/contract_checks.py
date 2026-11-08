"""Run with the bridge's own Python; only in-memory CRM and MCP transports."""
import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from assistant_bridge.server import Config, create_app


async def run():
    calls = []
    async def crm(request):
        assert request.headers["authorization"] == "Bearer qa-opaque-token"
        path = request.url.path
        calls.append((request.method, path))
        if path.endswith("/session"): return httpx.Response(200, json={"client_id": "qa", "scopes": ["crm.catalog.read"]})
        if path.endswith("/tool-schemas"): return httpx.Response(200, json=[{"name": "crm_get_access", "readOnlyHint": True,
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}])
        assert path.endswith("/tools/crm_get_access")
        return httpx.Response(200, json={"schema_version": 1, "data": {"projects": []}})
    app = create_app(Config("http://crm-internal/api/v1/assistant", "https://assistant.example/mcp", "https://crm.example/assistant-oauth"), httpx.MockTransport(crm))
    transport = httpx.ASGITransport(app=app)
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=transport, base_url="https://assistant.example") as client:
            response = await client.get("/.well-known/oauth-protected-resource/mcp")
            assert response.status_code == 200 and "crm.changes.prepare" in response.json()["scopes_supported"]
            response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            assert response.status_code == 401 and "resource_metadata=" in response.headers["www-authenticate"]
            assert not any(path.endswith("/tools/crm_get_access") for _, path in calls)
            response = await client.post("/mcp", content=b"x" * 65537)
            assert response.status_code == 413
        def client_factory(headers=None, timeout=None, auth=None):
            return httpx.AsyncClient(transport=transport, headers=headers, timeout=timeout, auth=auth)
        async with streamablehttp_client("https://assistant.example/mcp", headers={"Authorization": "Bearer qa-opaque-token"}, httpx_client_factory=client_factory) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ["crm_get_access"]
                result = await session.call_tool("crm_get_access", {})
                assert not result.isError and result.structuredContent["data"]["projects"] == []
                result = await session.call_tool("apply", {})
                assert result.isError
                result = await session.call_tool("crm_get_access", {"sql": "SELECT 1"})
                assert result.isError
    assert sum(path.endswith("/tools/crm_get_access") for _, path in calls) == 1
    print("Official MCP client: initialize/list/call, OAuth metadata, auth/body limits and forbidden tools passed")


if __name__ == "__main__": asyncio.run(run())
