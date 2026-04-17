from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from main import app


async def test_suggested_questions_route_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/messages/test-message/suggested-questions")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_suggested_questions_route_uses_service() -> None:
    context = type("ContextStub", (), {"app": type("AppStub", (), {"mode": "chat"})()})()
    with (
        patch("api_server.routes.conversation.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.conversation.SuggestedQuestionsService.get_suggested_questions",
            new=AsyncMock(return_value=["One?", "Two?"]),
        ) as suggested_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/messages/test-message/suggested-questions")

    assert response.status_code == 200
    assert response.json() == {"data": ["One?", "Two?"]}
    suggested_mock.assert_awaited_once()


async def test_more_like_this_route_returns_generation_unavailable() -> None:
    context = type("ContextStub", (), {"app": type("AppStub", (), {"mode": "completion"})()})()
    with (
        patch("api_server.routes.conversation.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.conversation.PublicGenerationBridge.run_more_like_this",
            new=AsyncMock(
                return_value=type(
                    "BlockingResponseStub",
                    (),
                    {"model_dump": lambda self, mode="json": {"task_id": "task-1", "data": {"answer": "ok"}}},
                )()
            ),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/messages/test-message/more-like-this")

    assert response.status_code == 200
    assert response.json()["task_id"] == "task-1"
