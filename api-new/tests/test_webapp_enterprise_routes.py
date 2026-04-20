from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api_server.routes import bootstrap as bootstrap_module
from main import app


async def test_webapp_access_mode_route_awaits_app_lookup_when_enterprise_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap_module.dify_config, "ENTERPRISE_ENABLED", True, raising=False)

    access_mode = type("AccessModeStub", (), {"access_mode": "private_all"})()
    with (
        patch(
            "api_server.routes.bootstrap.AppLookupService.get_app_id_by_code",
            new=AsyncMock(return_value="app-1"),
        ) as lookup_mock,
        patch(
            "api_server.routes.bootstrap.EnterpriseService.WebAppAuth.aget_app_access_mode_by_id",
            new=AsyncMock(return_value=access_mode),
        ) as enterprise_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/webapp/access-mode", params={"appCode": "demo-app"})

    assert response.status_code == 200
    assert response.json() == {"accessMode": "private_all"}
    lookup_mock.assert_awaited_once_with("demo-app")
    enterprise_mock.assert_awaited_once_with("app-1")


async def test_webapp_permission_route_awaits_passport_lookup_and_uses_enterprise_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap_module.dify_config, "ENTERPRISE_ENABLED", True, raising=False)

    access_mode = type("AccessModeStub", (), {"access_mode": "private"})()
    with (
        patch(
            "api_server.routes.bootstrap.EnterpriseService.WebAppAuth.aget_app_access_mode_by_id",
            new=AsyncMock(return_value=access_mode),
        ) as access_mode_mock,
        patch(
            "api_server.routes.bootstrap.extract_webapp_passport",
            new=AsyncMock(return_value="passport-token"),
        ) as passport_mock,
        patch(
            "api_server.routes.bootstrap.verify_passport",
            return_value={"user_id": "user-1"},
        ) as verify_mock,
        patch(
            "api_server.routes.bootstrap.EnterpriseService.WebAppAuth.ais_user_allowed_to_access_webapp",
            new=AsyncMock(return_value=True),
        ) as permission_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/api/webapp/permission",
                params={"appId": "app-1"},
                headers={"X-App-Code": "demo-app"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": True}
    access_mode_mock.assert_awaited_once_with("app-1")
    passport_mock.assert_awaited_once()
    verify_mock.assert_called_once_with("passport-token")
    permission_mock.assert_awaited_once_with("user-1", "app-1")
