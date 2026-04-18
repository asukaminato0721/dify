from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from main import app


class _ServiceApiContextStub:
    def __init__(self) -> None:
        self.app = type("AppStub", (), {"id": "app-1"})()
        self.tenant = type("TenantStub", (), {"id": "tenant-1"})()


class _SiteStub:
    title = "Dify"
    chat_color_theme = "#123456"
    chat_color_theme_inverted = False
    icon_type = "emoji"
    icon = "rocket"
    icon_background = "#ffffff"
    description = "Site description"
    copyright = "Dify"
    privacy_policy = "privacy"
    custom_disclaimer = "disclaimer"
    default_language = "en-US"
    show_workflow_steps = True
    use_icon_as_answer_icon = False


class _EndUserStub:
    id = str(uuid4())
    tenant_id = "tenant-1"
    app_id = "app-1"
    type = "session"
    external_user_id = "external-1"
    name = "Ada"
    is_anonymous = False
    session_id = "session-1"
    created_at = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    updated_at = datetime(2026, 4, 18, 12, 5, tzinfo=UTC)


async def test_service_api_index_route() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/v1/")

    assert response.status_code == 200
    assert response.json()["welcome"] == "Dify OpenAPI"
    assert response.json()["api_version"] == "v1"


async def test_service_api_site_route_uses_auth_and_resource_services() -> None:
    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=_ServiceApiContextStub()),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiResourceService.get_site",
            new=AsyncMock(return_value=_SiteStub()),
        ) as site_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/v1/site", headers={"Authorization": "Bearer app-token"})

    assert response.status_code == 200
    assert response.json()["title"] == "Dify"
    auth_mock.assert_awaited_once()
    site_mock.assert_awaited_once_with(app_id="app-1")


async def test_service_api_end_user_route_returns_scoped_end_user() -> None:
    context = _ServiceApiContextStub()
    end_user = _EndUserStub()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiResourceService.get_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(f"/v1/end-users/{end_user.id}", headers={"Authorization": "Bearer app-token"})

    assert response.status_code == 200
    assert response.json()["id"] == end_user.id
    assert response.json()["tenant_id"] == "tenant-1"
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        app_id="app-1",
        end_user_id=end_user.id,
    )
