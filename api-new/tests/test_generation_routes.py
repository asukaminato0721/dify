from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from fastapi.responses import JSONResponse, StreamingResponse

from main import app


class _AppStub:
    def __init__(self, mode: str) -> None:
        self.mode = mode


class _ContextStub:
    def __init__(self, mode: str) -> None:
        self.app = _AppStub(mode)


async def test_completion_route_uses_generation_bridge() -> None:
    context = _ContextStub("completion")
    with (
        patch("api_server.routes.generation.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.generation.PublicGenerationBridge.run_completion",
            new=AsyncMock(return_value=JSONResponse(content={"ok": True})),
        ) as completion_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/completion-messages", json={"inputs": {}, "query": "hello"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    completion_mock.assert_awaited_once()


async def _stream() -> AsyncIterator[str]:
    yield "data: hi\n\n"


async def test_chat_route_uses_generation_bridge() -> None:
    context = _ContextStub("chat")
    with (
        patch("api_server.routes.generation.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.generation.PublicGenerationBridge.run_chat",
            new=AsyncMock(return_value=StreamingResponse(_stream(), media_type="text/event-stream")),
        ) as chat_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/chat-messages", json={"inputs": {}, "query": "hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chat_mock.assert_awaited_once()


async def test_workflow_route_uses_generation_bridge() -> None:
    context = _ContextStub("workflow")
    with (
        patch("api_server.routes.generation.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.generation.PublicGenerationBridge.run_workflow",
            new=AsyncMock(return_value=JSONResponse(content={"ok": True})),
        ) as workflow_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/api/workflows/run", json={"inputs": {}})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    workflow_mock.assert_awaited_once()
