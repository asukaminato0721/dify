from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

import api_server.routes.bootstrap as bootstrap_routes
from api_server.errors import bad_request
from api_server.models.app import AppMode, CreatorUserRole
from api_server.routes.workflow_events import get_workflow_events
from api_server.services.generation_bridge import ChatMessagePayload, CompletionMessagePayload, WorkflowRunPayload
from api_server.services.webapp_context import WebappContext
from api_server.services.workflow_events import WorkflowEventsService, WorkflowRunRecord
from main import app
from core.mcp import types as mcp_types


async def test_health_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ping_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/console/api/ping")

    assert response.status_code == 200
    assert response.json() == {"result": "pong"}


async def test_system_features_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/system-features")

    assert response.status_code == 200
    payload = response.json()
    assert "app_dsl_version" in payload
    assert "enable_email_password_login" in payload


async def test_webapp_access_mode_defaults_to_public_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/webapp/access-mode")

    assert response.status_code == 200
    assert response.json() == {"accessMode": "public"}


async def test_webapp_permission_defaults_to_true_when_enterprise_disabled() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-App-Code": "demo-app"},
    ) as client:
        response = await client.get("/api/webapp/permission", params={"appId": "demo-id"})

    assert response.status_code == 200
    assert response.json() == {"result": True}


async def test_webapp_access_mode_uses_async_enterprise_service_when_enabled() -> None:
    with (
        patch.object(bootstrap_routes.dify_config, "ENTERPRISE_ENABLED", True),
        patch(
            "api_server.routes.bootstrap.AppLookupService.get_app_id_by_code",
            new=AsyncMock(return_value="app-1"),
        ) as lookup_mock,
        patch(
            "api_server.routes.bootstrap.EnterpriseService.WebAppAuth.aget_app_access_mode_by_id",
            new=AsyncMock(return_value=type("AccessModeStub", (), {"access_mode": "private"})()),
        ) as access_mode_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/webapp/access-mode", params={"appCode": "demo-app"})

    assert response.status_code == 200
    assert response.json() == {"accessMode": "private"}
    lookup_mock.assert_awaited_once_with("demo-app")
    access_mode_mock.assert_awaited_once_with("app-1")


async def test_webapp_permission_uses_async_enterprise_service_when_private() -> None:
    with (
        patch.object(bootstrap_routes.dify_config, "ENTERPRISE_ENABLED", True),
        patch(
            "api_server.routes.bootstrap.EnterpriseService.WebAppAuth.aget_app_access_mode_by_id",
            new=AsyncMock(return_value=type("AccessModeStub", (), {"access_mode": "private"})()),
        ) as access_mode_mock,
        patch(
            "api_server.routes.bootstrap.extract_webapp_passport",
            new=AsyncMock(return_value="passport-token"),
        ),
        patch("api_server.routes.bootstrap.verify_passport", return_value={"user_id": "user-1"}),
        patch(
            "api_server.routes.bootstrap.EnterpriseService.WebAppAuth.ais_user_allowed_to_access_webapp",
            new=AsyncMock(return_value=True),
        ) as permission_mock,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-App-Code": "demo-app"},
        ) as client:
            response = await client.get("/api/webapp/permission", params={"appId": "app-1"})

    assert response.status_code == 200
    assert response.json() == {"result": True}
    access_mode_mock.assert_awaited_once_with("app-1")
    permission_mock.assert_awaited_once_with("user-1", "app-1")


async def test_site_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/site")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_remote_file_info_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/remote-files/https%3A%2F%2Fexample.com%2Ftest.txt")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_remote_file_upload_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/remote-files/upload", json={"url": "https://example.com/test.txt"})

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_file_upload_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_tool_file_route_rejects_invalid_signature() -> None:
    file_id = str(uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            f"/files/tools/{file_id}.png",
            params={"timestamp": "1", "nonce": "nonce", "sign": "bad"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_request"


async def test_tool_file_route_streams_signed_file() -> None:
    file_id = str(uuid4())
    graph_file = type("GraphFileStub", (), {"filename": "tool.png", "mime_type": "image/png", "size": 3})()

    with (
        patch("api_server.routes.files.verify_tool_file_signature", return_value=True),
        patch(
            "api_server.routes.files.ToolFileManager.get_file_generator_by_tool_file_id",
            return_value=(iter([b"abc"]), graph_file),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                f"/files/tools/{file_id}.png",
                params={"timestamp": "1", "nonce": "nonce", "sign": "good"},
            )

    assert response.status_code == 200
    assert response.content == b"abc"
    assert response.headers["content-length"] == "3"


async def test_plugin_upload_route_creates_tool_file() -> None:
    user = type("UserStub", (), {"id": "end-user-1"})()
    tool_file = type(
        "ToolFileStub",
        (),
        {
            "id": "tool-file-1",
            "name": "plugin.png",
            "size": 4,
            "mimetype": "image/png",
            "original_url": None,
            "user_id": "end-user-1",
            "tenant_id": "tenant-1",
            "conversation_id": None,
            "file_key": "tools/tenant-1/plugin.png",
        },
    )()

    with (
        patch("api_server.routes.files._get_or_create_plugin_user", new=AsyncMock(return_value=user)),
        patch("api_server.routes.files.verify_plugin_file_signature", return_value=True),
        patch("api_server.routes.files.ToolFileManager.create_file_by_raw", return_value=tool_file),
        patch("api_server.routes.files.ToolFileManager.sign_file", return_value="/files/tools/tool-file-1.png"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/files/upload/for-plugin",
                params={
                    "timestamp": "1",
                    "nonce": "nonce",
                    "sign": "good",
                    "tenant_id": "tenant-1",
                    "user_id": "end-user-1",
                },
                files={"file": ("plugin.png", b"data", "image/png")},
            )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == "tool-file-1"
    assert payload["preview_url"] == "/files/tools/tool-file-1.png"
    assert payload["mime_type"] == "image/png"


async def test_conversation_list_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/conversations")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_message_list_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/messages", params={"conversation_id": str(uuid4())})

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_saved_messages_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/saved-messages")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_stop_chat_task_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/chat-messages/test-task/stop")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_completion_generation_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/completion-messages", json={"inputs": {}, "query": ""})

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_chat_generation_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/chat-messages", json={"inputs": {}, "query": "hello"})

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_workflow_generation_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/workflows/run", json={"inputs": {}})

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_workflow_events_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/workflow/test-task/events")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_mcp_notification_route_returns_202() -> None:
    mcp_server = type("McpServerStub", (), {"tenant_id": "tenant-1", "id": "server-1"})()
    app_stub = type("AppStub", (), {"tenant_id": "tenant-1", "id": "app-1", "mode": "chat", "app_model_config": None})()

    with (
        patch("api_server.routes.mcp._load_mcp_server_and_app", new=AsyncMock(return_value=(mcp_server, app_stub))),
        patch("api_server.routes.mcp._get_user_input_form", new=AsyncMock(return_value=[])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/mcp/server/demo/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )

    assert response.status_code == 202


async def test_mcp_request_route_returns_jsonrpc_payload() -> None:
    mcp_server = type("McpServerStub", (), {"tenant_id": "tenant-1", "id": "server-1"})()
    app_stub = type("AppStub", (), {"tenant_id": "tenant-1", "id": "app-1", "mode": "chat", "app_model_config": None})()
    response_payload = mcp_types.JSONRPCResponse(jsonrpc="2.0", id=1, result={"ok": True})

    with (
        patch("api_server.routes.mcp._load_mcp_server_and_app", new=AsyncMock(return_value=(mcp_server, app_stub))),
        patch("api_server.routes.mcp._get_user_input_form", new=AsyncMock(return_value=[])),
        patch("api_server.routes.mcp._retrieve_end_user", new=AsyncMock(return_value=None)),
        patch("api_server.routes.mcp.handle_mcp_request", return_value=response_payload) as handler_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/mcp/server/demo/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            )

    assert response.status_code == 200
    assert response.json() == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    handler_mock.assert_called_once()


async def test_trigger_plugin_route_rejects_invalid_uuid() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/triggers/plugin/not-a-uuid")

    assert response.status_code == 404
    assert response.json() == {"error": "Invalid endpoint ID"}


async def test_trigger_plugin_route_uses_trigger_service() -> None:
    endpoint_id = str(uuid4())

    class _ResponseStub:
        status_code = 200
        mimetype = "application/json"
        headers = {}

        @staticmethod
        def get_data():
            return b'{"ok":true}'

    trigger_service = type("TriggerServiceStub", (), {"process_endpoint": object()})()
    builder_service = type("BuilderServiceStub", (), {"process_builder_validation_endpoint": object()})()

    with patch(
        "api_server.routes.trigger._build_flask_request",
        new=AsyncMock(return_value=object()),
    ), patch(
        "api_server.routes.trigger._get_trigger_services",
        return_value=(trigger_service, builder_service),
    ), patch(
        "api_server.routes.trigger.asyncio.to_thread",
        new=AsyncMock(return_value=_ResponseStub()),
    ) as trigger_mock:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(f"/triggers/plugin/{endpoint_id}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    trigger_mock.assert_awaited()


async def test_trigger_webhook_route_returns_json_payload() -> None:
    webhook_trigger = type(
        "WebhookTriggerStub",
        (),
        {"tenant_id": "tenant-1", "app_id": "app-1", "node_id": "node-1", "webhook_id": "webhook-1"},
    )()
    webhook_service = type(
        "WebhookServiceStub",
        (),
        {
            "trigger_workflow_execution": object(),
            "generate_webhook_response": object(),
        },
    )()

    with (
        patch("api_server.routes.trigger._build_flask_request", new=AsyncMock(return_value=object())),
        patch("api_server.routes.trigger._get_webhook_service", return_value=webhook_service),
        patch(
            "api_server.routes.trigger.asyncio.to_thread",
            new=AsyncMock(
                side_effect=[
                    (webhook_trigger, object(), {"data": {}}, {"method": "POST"}, None),
                    None,
                    ({"result": "success"}, 200),
                ]
            ),
        ) as to_thread_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(f"/triggers/webhook/{uuid4()}", json={"hello": "world"})

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    assert to_thread_mock.await_count == 3


async def test_trigger_webhook_debug_route_returns_conflict_without_listener() -> None:
    webhook_trigger = type(
        "WebhookTriggerStub",
        (),
        {
            "tenant_id": "tenant-1",
            "app_id": "app-1",
            "node_id": "node-1",
            "webhook_id": "webhook-1",
            "webhook_url": "https://example.com/webhook",
        },
    )()
    webhook_service = type("WebhookServiceStub", (), {"build_workflow_inputs": object()})()
    debug_helpers = (
        type("BusStub", (), {"dispatch": staticmethod(lambda **kwargs: 0)}),
        type("WebhookDebugEventStub", (), {"__init__": lambda self, **kwargs: None}),
        lambda *, tenant_id, app_id, node_id: "pool-key",
    )

    with (
        patch("api_server.routes.trigger._build_flask_request", new=AsyncMock(return_value=object())),
        patch("api_server.routes.trigger._get_webhook_service", return_value=webhook_service),
        patch("api_server.routes.trigger._get_trigger_debug_helpers", return_value=debug_helpers),
        patch(
            "api_server.routes.trigger.asyncio.to_thread",
            new=AsyncMock(
                side_effect=[
                    (webhook_trigger, object(), {"data": {}}, {"method": "POST"}, None),
                    {"ok": True},
                ]
            ),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(f"/triggers/webhook-debug/{uuid4()}", json={"hello": "world"})

    assert response.status_code == 409
    assert response.json()["error"] == "No active debug listener"


async def test_inner_enterprise_mail_route_requires_valid_key() -> None:
    with patch("api_server.routes.inner_api._ensure_setup", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/inner/api/enterprise/mail",
                json={"to": ["a@example.com"], "subject": "s", "body": "b"},
            )

    assert response.status_code == 404 or response.status_code == 401


async def test_inner_enterprise_mail_route_uses_wrapper() -> None:
    with (
        patch("api_server.routes.inner_api._ensure_setup", new=AsyncMock()),
        patch("api_server.routes.inner_api._check_inner_api_access"),
        patch("api_server.routes.inner_api.asyncio.to_thread", new=AsyncMock(return_value={"message": "success"})),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Inner-Api-Key": "test-key"},
        ) as client:
            response = await client.post(
                "/inner/api/enterprise/mail",
                json={"to": ["a@example.com"], "subject": "s", "body": "b"},
            )

    assert response.status_code == 200
    assert response.json() == {"message": "success"}


async def test_inner_workspace_route_uses_wrapper() -> None:
    payload = {"message": "enterprise workspace created.", "tenant": {"id": "tenant-1"}}
    with (
        patch("api_server.routes.inner_api._ensure_setup", new=AsyncMock()),
        patch("api_server.routes.inner_api._check_inner_api_access"),
        patch("api_server.routes.inner_api.asyncio.to_thread", new=AsyncMock(return_value=(payload, 200))),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Inner-Api-Key": "test-key"},
        ) as client:
            response = await client.post(
                "/inner/api/enterprise/workspace",
                json={"name": "Demo", "owner_email": "owner@example.com"},
            )

    assert response.status_code == 200
    assert response.json() == payload


async def test_inner_dsl_export_route_uses_wrapper() -> None:
    payload = {"data": "dsl"}
    with (
        patch("api_server.routes.inner_api._ensure_setup", new=AsyncMock()),
        patch("api_server.routes.inner_api._check_inner_api_access"),
        patch("api_server.routes.inner_api.asyncio.to_thread", new=AsyncMock(return_value=(payload, 200))),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Inner-Api-Key": "test-key"},
        ) as client:
            response = await client.get("/inner/api/enterprise/apps/app-1/dsl")

    assert response.status_code == 200
    assert response.json() == payload


async def test_inner_plugin_upload_file_request_uses_wrapper() -> None:
    with (
        patch("api_server.routes.inner_api_plugin._ensure_setup", new=AsyncMock()),
        patch("api_server.routes.inner_api_plugin._check_plugin_inner_api_access"),
        patch(
            "api_server.routes.inner_api_plugin._prepare_plugin_request",
            new=AsyncMock(
                return_value=(
                    type("UserStub", (), {"id": "user-1"})(),
                    type("TenantStub", (), {"id": "tenant-1"})(),
                    type("PayloadStub", (), {"filename": "a.txt", "mimetype": "text/plain"})(),
                )
            ),
        ),
        patch(
            "api_server.routes.inner_api_plugin.get_signed_file_url_for_plugin",
            return_value="https://example.com/upload",
        ),
        patch(
            "api_server.routes.inner_api_plugin._get_backwards_base",
            return_value=type("RespStub", (), {"__init__": lambda self, **kwargs: setattr(self, "_data", kwargs), "model_dump": lambda self: self._data}),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Inner-Api-Key": "plugin-key"},
        ) as client:
            response = await client.post(
                "/inner/api/upload/file/request",
                json={"tenant_id": "tenant-1", "user_id": "user-1", "filename": "a.txt", "mimetype": "text/plain"},
            )

    assert response.status_code == 200
    assert response.json()["data"]["url"] == "https://example.com/upload"


async def test_inner_plugin_llm_route_returns_streaming_response() -> None:
    with (
        patch("api_server.routes.inner_api_plugin._ensure_setup", new=AsyncMock()),
        patch("api_server.routes.inner_api_plugin._check_plugin_inner_api_access"),
        patch(
            "api_server.routes.inner_api_plugin._prepare_plugin_request",
            new=AsyncMock(
                return_value=(
                    type("UserStub", (), {"id": "user-1"})(),
                    type("TenantStub", (), {"id": "tenant-1"})(),
                    object(),
                )
            ),
        ),
        patch(
            "api_server.routes.inner_api_plugin.asyncio.to_thread",
            new=AsyncMock(return_value=iter([b"payload"])),
        ),
        patch("api_server.routes.inner_api_plugin._get_backwards_model"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Inner-Api-Key": "plugin-key"},
        ) as client:
            response = await client.post(
                "/inner/api/invoke/llm",
                json={"tenant_id": "tenant-1", "user_id": "user-1", "provider": "openai", "model": "gpt", "mode": "chat", "completion_params": {}, "prompt_messages": []},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


async def test_console_features_route_uses_fastapi_auth_helper() -> None:
    payload = {"billing": {"enabled": False}}
    account = type("AccountStub", (), {"current_tenant_id": "tenant-1"})()

    with (
        patch("api_server.routes.console_misc._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_misc._resolve_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_misc.asyncio.to_thread", new=AsyncMock(return_value=payload)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/console/api/features")

    assert response.status_code == 200
    assert response.json() == payload


async def test_console_schema_definitions_route_uses_fastapi_auth_helper() -> None:
    payload = [{"name": "schema-1", "schema": {"type": "object"}}]
    account = type("AccountStub", (), {"current_tenant_id": "tenant-1"})()

    with (
        patch("api_server.routes.console_misc._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_misc._resolve_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_misc.asyncio.to_thread", new=AsyncMock(return_value=payload)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/console/api/spec/schema-definitions")

    assert response.status_code == 200
    assert response.json() == payload


async def test_console_notification_route_uses_fastapi_auth_helper() -> None:
    payload = {"should_show": False, "notifications": []}
    account = type("AccountStub", (), {"id": "acc-1", "current_tenant_id": "tenant-1", "interface_language": "en-US"})()

    with (
        patch("api_server.routes.console_assets._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_assets._ensure_cloud"),
        patch("api_server.routes.console_assets._resolve_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_assets.asyncio.to_thread", new=AsyncMock(return_value={"shouldShow": False})),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/console/api/notification")

    assert response.status_code == 200
    assert response.json() == payload


async def test_console_files_upload_config_route_uses_fastapi_auth_helper() -> None:
    account = type("AccountStub", (), {"current_tenant_id": "tenant-1"})()

    with (
        patch("api_server.routes.console_assets._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_assets._resolve_console_account", new=AsyncMock(return_value=account)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/console/api/files/upload")

    assert response.status_code == 200
    assert "file_size_limit" in response.json()


async def test_console_remote_file_info_route_uses_fastapi_auth_helper() -> None:
    account = type("AccountStub", (), {"current_tenant_id": "tenant-1"})()
    head_response = type(
        "RespStub",
        (),
        {
            "status_code": 200,
            "headers": {"Content-Type": "text/plain", "Content-Length": "12"},
            "raise_for_status": lambda self: None,
        },
    )()

    with (
        patch("api_server.routes.console_assets._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_assets._resolve_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_assets.asyncio.to_thread", new=AsyncMock(return_value=head_response)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/console/api/remote-files/https%3A%2F%2Fexample.com%2Fa.txt")

    assert response.status_code == 200
    assert response.json() == {"file_type": "text/plain", "file_length": 12}


async def test_console_login_route_sets_auth_cookies() -> None:
    account = type("AccountStub", (), {"id": "acc-1", "name": "User"})()
    tenant = type("TenantStub", (), {"id": "tenant-1"})()
    token_pair = type(
        "TokenPairStub",
        (),
        {"access_token": "access-token", "refresh_token": "refresh-token", "csrf_token": "csrf-token"},
    )()

    with (
        patch("api_server.routes.console_auth._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_auth._require_email_password_login", new=AsyncMock()),
        patch("api_server.routes.console_auth._decrypt_password", return_value="plain-password"),
        patch("api_server.routes.console_auth.BillingService.is_email_in_freeze", return_value=False),
        patch("api_server.routes.console_auth.AccountService.is_login_error_rate_limit", return_value=False),
        patch("api_server.routes.console_auth._authenticate_account_with_case_fallback", return_value=account),
        patch("api_server.routes.console_auth.TenantService.get_join_tenants", return_value=[tenant]),
        patch("api_server.routes.console_auth.AccountService.login", return_value=token_pair),
        patch("api_server.routes.console_auth.AccountService.reset_login_error_rate_limit"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/console/api/login",
                json={"email": "user@example.com", "password": "encrypted"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    set_cookie = "\n".join(response.headers.get_list("set-cookie"))
    assert "access-token" in set_cookie
    assert "refresh-token" in set_cookie
    assert "csrf-token" in set_cookie


async def test_console_logout_route_clears_auth_cookies() -> None:
    account = type("AccountStub", (), {"id": "acc-1"})()

    with (
        patch("api_server.routes.console_auth._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_auth._resolve_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_auth.AccountService.logout"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/console/api/logout",
                cookies={"access_token": "access-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    set_cookie = "\n".join(response.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "expires=" in set_cookie.lower()


async def test_console_refresh_token_route_sets_new_auth_cookies() -> None:
    token_pair = type(
        "TokenPairStub",
        (),
        {"access_token": "next-access", "refresh_token": "next-refresh", "csrf_token": "next-csrf"},
    )()

    with patch("api_server.routes.console_auth.AccountService.refresh_token", return_value=token_pair):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/console/api/refresh-token",
                cookies={"refresh_token": "refresh-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    assert "next-access" in "\n".join(response.headers.get_list("set-cookie"))


async def test_console_forgot_password_validity_route_returns_new_token() -> None:
    with (
        patch("api_server.routes.console_auth._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_auth._require_email_password_login", new=AsyncMock()),
        patch("api_server.routes.console_auth.AccountService.is_forgot_password_error_rate_limit", return_value=False),
        patch(
            "api_server.routes.console_auth.AccountService.get_reset_password_data",
            return_value={"email": "user@example.com", "code": "123456"},
        ),
        patch("api_server.routes.console_auth.AccountService.revoke_reset_password_token"),
        patch(
            "api_server.routes.console_auth.AccountService.generate_reset_password_token",
            return_value=("123456", "reset-token-2"),
        ),
        patch("api_server.routes.console_auth.AccountService.reset_forgot_password_error_rate_limit"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/console/api/forgot-password/validity",
                json={"email": "user@example.com", "code": "123456", "token": "reset-token-1"},
            )

    assert response.status_code == 200
    assert response.json() == {"is_valid": True, "email": "user@example.com", "token": "reset-token-2"}


async def test_console_oauth_login_route_redirects_to_provider() -> None:
    provider = type("ProviderStub", (), {"get_authorization_url": lambda self, invite_token=None: "https://oauth.example.com/auth"})()

    with patch("api_server.routes.console_auth._get_oauth_providers", return_value={"github": provider}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", follow_redirects=False) as client:
            response = await client.get("/console/api/oauth/login/github")

    assert response.status_code == 302
    assert response.headers["location"] == "https://oauth.example.com/auth"


async def test_console_oauth_authorize_route_sets_cookies_and_redirects() -> None:
    provider = type(
        "ProviderStub",
        (),
        {
            "get_access_token": lambda self, code: "provider-token",
            "get_user_info": lambda self, token: type("UserInfoStub", (), {"email": "user@example.com", "id": "oauth-id", "name": "OAuth User"})(),
        },
    )()
    account = type("AccountStub", (), {"id": "acc-1", "status": "active"})()
    token_pair = type(
        "TokenPairStub",
        (),
        {"access_token": "oauth-access", "refresh_token": "oauth-refresh", "csrf_token": "oauth-csrf"},
    )()

    with (
        patch("api_server.routes.console_auth._get_oauth_providers", return_value={"github": provider}),
        patch("api_server.routes.console_auth.RegisterService.is_valid_invite_token", return_value=False),
        patch("api_server.routes.console_auth._generate_oauth_account", return_value=(account, True)),
        patch("api_server.routes.console_auth.TenantService.create_owner_tenant_if_not_exist"),
        patch("api_server.routes.console_auth.AccountService.login", return_value=token_pair),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", follow_redirects=False) as client:
            response = await client.get("/console/api/oauth/authorize/github", params={"code": "oauth-code"})

    assert response.status_code == 302
    assert "oauth_new_user=true" in response.headers["location"]
    assert "oauth-access" in "\n".join(response.headers.get_list("set-cookie"))


async def test_console_oauth_provider_authorize_route_uses_fastapi_auth_helper() -> None:
    account = type("AccountStub", (), {"id": "acc-1"})()
    oauth_app = type("OAuthAppStub", (), {"client_id": "client-1"})()

    with (
        patch("api_server.routes.console_auth._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_auth._require_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_auth.OAuthServerService.get_oauth_provider_app", return_value=oauth_app),
        patch("api_server.routes.console_auth.OAuthServerService.sign_oauth_authorization_code", return_value="auth-code"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/console/api/oauth/provider/authorize", json={"client_id": "client-1"})

    assert response.status_code == 200
    assert response.json() == {"code": "auth-code"}


async def test_console_oauth_provider_account_route_requires_bearer_header() -> None:
    oauth_app = type("OAuthAppStub", (), {"client_id": "client-1"})()

    with (
        patch("api_server.routes.console_auth._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_auth.OAuthServerService.get_oauth_provider_app", return_value=oauth_app),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post("/console/api/oauth/provider/account", json={"client_id": "client-1"})

    assert response.status_code == 401
    assert response.json() == {"error": "Authorization header is required"}
    assert response.headers["www-authenticate"] == "Bearer"


async def test_console_datasource_binding_route_persists_authenticated_binding() -> None:
    account = type("AccountStub", (), {"current_tenant_id": "tenant-1"})()

    with (
        patch("api_server.routes.console_auth._require_console_account", new=AsyncMock(return_value=account)),
        patch(
            "api_server.routes.console_auth._exchange_notion_access_token",
            return_value=("notion-token", "Workspace", None, "workspace-1"),
        ),
        patch("api_server.routes.console_auth._upsert_notion_binding", new=AsyncMock()),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/console/api/oauth/data-source/binding/notion", params={"code": "oauth-code"})

    assert response.status_code == 200
    assert response.json() == {"result": "success"}


async def test_console_api_key_binding_route_uses_fastapi_auth_helper() -> None:
    account = type("AccountStub", (), {"current_tenant_id": "tenant-1"})()

    with (
        patch("api_server.routes.console_auth._ensure_console_setup", new=AsyncMock()),
        patch("api_server.routes.console_auth._require_console_account", new=AsyncMock(return_value=account)),
        patch("api_server.routes.console_auth.ApiKeyAuthService.validate_api_key_auth_args"),
        patch("api_server.routes.console_auth.ApiKeyAuthService.create_provider_auth"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/console/api/api-key-auth/data-source/binding",
                json={"category": "datasource", "provider": "notion", "credentials": {"auth_type": "api_key"}},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}


async def test_finished_workflow_events_return_sse_payload() -> None:
    context = WebappContext(
        app=type("AppStub", (), {"mode": AppMode.WORKFLOW, "id": "app-1"})(),
        site=type("SiteStub", (), {})(),
        end_user=type("EndUserStub", (), {"id": "end-user-1", "session_id": "session-1"})(),
        tenant=type("TenantStub", (), {"id": "tenant-1"})(),
        app_model_config=None,
        workflow=None,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/workflow/workflow-run-1/events",
            "headers": [],
            "query_string": b"",
        }
    )

    with (
        patch("api_server.routes.workflow_events.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.workflow_events.WorkflowEventsService.get_accessible_workflow_run",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "api_server.routes.workflow_events.WorkflowEventsService.stream_events",
            return_value=iter(["event: ping\n\n"]),
        ),
    ):
        response = await get_workflow_events(request, "workflow-run-1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_finished_workflow_service_streams_single_sse_event() -> None:
    finished_run = WorkflowRunRecord(
        id="workflow-run-1",
        workflow_id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        inputs={"query": "hello"},
        status="succeeded",
        outputs={"answer": "done"},
        error=None,
        elapsed_time=1.5,
        total_tokens=42,
        total_steps=3,
        created_at=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 4, 18, 12, 1, tzinfo=UTC),
        exceptions_count=0,
        created_by_role=CreatorUserRole.END_USER,
        created_by="end-user-1",
    )
    end_user = type("EndUserStub", (), {"id": "end-user-1", "session_id": "session-1"})()

    events = list(
        WorkflowEventsService.stream_events(
            app_mode=AppMode.WORKFLOW,
            workflow_run=finished_run,
            end_user=end_user,
            include_state_snapshot=False,
        )
    )

    assert len(events) == 1
    assert '"event":"workflow_finished"' in events[0]
    assert '"workflow_run_id":"workflow-run-1"' in events[0]


def test_generation_payload_models_validate_response_mode() -> None:
    assert CompletionMessagePayload(inputs={}, query="", response_mode="blocking").response_mode == "blocking"
    assert ChatMessagePayload(inputs={}, query="hi", response_mode="streaming").response_mode == "streaming"
    assert WorkflowRunPayload(inputs={}, response_mode=None).response_mode is None


async def test_file_preview_missing_file() -> None:
    with patch(
        "api_server.services.file_access.FileAccessService.get_upload_file",
        new=AsyncMock(side_effect=bad_request("file_not_found", "File not found")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(f"/files/{uuid4()}/file-preview")

    assert response.status_code == 400
    assert response.json()["code"] == "file_not_found"


async def test_passport_requires_app_code() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/passport")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_app_code"


async def test_login_status_without_app_code() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/login/status")

    assert response.status_code == 200
    assert response.json() == {"logged_in": False, "app_logged_in": False}


async def test_login_is_rejected_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/login", json={"email": "user@example.com", "password": "abc12345"})

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


async def test_email_code_login_is_rejected_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/email-code-login", json={"email": "user@example.com"})

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


async def test_forgot_password_is_rejected_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"
