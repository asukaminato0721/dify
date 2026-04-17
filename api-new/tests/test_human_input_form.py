from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from main import app


async def test_get_human_input_form_route_returns_service_payload() -> None:
    expected_payload = {
        "form_content": "<p>Hello</p>",
        "inputs": [],
        "resolved_default_values": {},
        "user_actions": [],
        "expiration_time": 1,
    }

    with (
        patch("api_server.routes.human_input_form.HumanInputFormService.check_rate_limit"),
        patch(
            "api_server.routes.human_input_form.HumanInputFormService.get_form_definition_response",
            new=AsyncMock(return_value=expected_payload),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/form/human_input/test-token")

    assert response.status_code == 200
    assert response.json() == expected_payload


async def test_submit_human_input_form_route_calls_service() -> None:
    with (
        patch("api_server.routes.human_input_form.HumanInputFormService.check_rate_limit"),
        patch(
            "api_server.routes.human_input_form.HumanInputFormService.submit_form_by_token",
            new=AsyncMock(),
        ) as submit_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/api/form/human_input/test-token",
                json={"inputs": {"content": "ok"}, "action": "approve"},
            )

    assert response.status_code == 200
    assert response.json() == {}
    submit_mock.assert_awaited_once_with(
        form_token="test-token",
        selected_action_id="approve",
        form_data={"content": "ok"},
    )


async def test_submit_human_input_form_requires_action() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/form/human_input/test-token", json={"inputs": {"content": "ok"}})

    assert response.status_code == 422
