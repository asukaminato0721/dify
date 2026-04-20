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
