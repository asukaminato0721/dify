from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from main import app


class _ServiceApiContextStub:
    def __init__(self) -> None:
        self.app = type("AppStub", (), {"id": "app-1", "mode": type("ModeStub", (), {"value": "chat"})()})()
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


async def test_service_api_parameters_route_uses_app_service() -> None:
    context = _ServiceApiContextStub()
    parameters_payload = {
        "opening_statement": None,
        "suggested_questions": [],
        "suggested_questions_after_answer": {"enabled": False},
        "speech_to_text": {"enabled": False},
        "text_to_speech": {"enabled": False},
        "retriever_resource": {"enabled": True},
        "annotation_reply": {"enabled": False},
        "more_like_this": {"enabled": False},
        "user_input_form": [],
        "sensitive_word_avoidance": {"enabled": False},
        "file_upload": {"enabled": False},
        "system_parameters": {
            "image_file_size_limit": 0,
            "video_file_size_limit": 0,
            "audio_file_size_limit": 0,
            "file_size_limit": 0,
            "workflow_file_upload_limit": 0,
        },
    }
    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAppService.get_parameters",
            new=AsyncMock(return_value=parameters_payload),
        ) as parameters_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/v1/parameters", headers={"Authorization": "Bearer app-token"})

    assert response.status_code == 200
    assert response.json() == parameters_payload
    auth_mock.assert_awaited_once()
    parameters_mock.assert_awaited_once_with(app=context.app)


async def test_service_api_meta_route_uses_app_service() -> None:
    context = _ServiceApiContextStub()
    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAppService.get_meta",
            new=AsyncMock(return_value={"tool_icons": {"search": {"content": "S"}}}),
        ) as meta_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/v1/meta", headers={"Authorization": "Bearer app-token"})

    assert response.status_code == 200
    assert response.json() == {"tool_icons": {"search": {"content": "S"}}}
    auth_mock.assert_awaited_once()
    meta_mock.assert_awaited_once_with(app=context.app)


async def test_service_api_info_route_uses_app_service() -> None:
    context = _ServiceApiContextStub()
    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAppService.get_info",
            new=AsyncMock(
                return_value={
                    "name": "Weather Bot",
                    "description": "Answers weather questions",
                    "tags": ["weather"],
                    "mode": "chat",
                    "author_name": "Ada",
                }
            ),
        ) as info_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/v1/info", headers={"Authorization": "Bearer app-token"})

    assert response.status_code == 200
    assert response.json()["name"] == "Weather Bot"
    auth_mock.assert_awaited_once()
    info_mock.assert_awaited_once_with(app=context.app)


async def test_service_api_file_upload_route_uses_end_user_and_file_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()
    upload_payload = {
        "id": "file-1",
        "name": "hello.txt",
        "size": 5,
        "extension": "txt",
        "mime_type": "text/plain",
        "created_by": "end-user-1",
        "created_at": 1710000000,
        "url": "/files/file-1",
    }

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ServiceApiFileService.upload_file",
            new=AsyncMock(return_value=upload_payload),
        ) as upload_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/files/upload",
                headers={"Authorization": "Bearer app-token"},
                files={"file": ("hello.txt", b"hello", "text/plain")},
                data={"user": "session-1"},
            )

    assert response.status_code == 201
    assert response.json() == upload_payload
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    upload_mock.assert_awaited_once()


async def test_service_api_file_preview_route_streams_owned_file(tmp_path: Path) -> None:
    context = _ServiceApiContextStub()
    preview_file = tmp_path / "hello.txt"
    preview_file.write_text("hello")
    upload_file = type(
        "UploadFileStub",
        (),
        {"name": "hello.txt", "mime_type": "text/plain"},
    )()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiFileService.get_owned_upload_file",
            new=AsyncMock(return_value=upload_file),
        ) as owned_file_mock,
        patch(
            "api_server.routes.service_api.ServiceApiFileService.get_file_path",
            return_value=preview_file,
        ) as path_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/files/file-1/preview",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.text == "hello"
    auth_mock.assert_awaited_once()
    owned_file_mock.assert_awaited_once_with(app=context.app, file_id="file-1")
    path_mock.assert_called_once_with(upload_file)


async def test_service_api_messages_route_uses_native_message_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()
    payload = {"limit": 20, "has_more": False, "data": []}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ConversationMessageService.list_messages",
            new=AsyncMock(return_value=payload),
        ) as messages_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/messages",
                headers={"Authorization": "Bearer app-token"},
                params={"conversation_id": "conversation-1", "user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    messages_mock.assert_awaited_once_with(
        app_id="app-1",
        end_user=end_user,
        conversation_id="conversation-1",
        first_id=None,
        limit=20,
    )


async def test_service_api_message_feedback_route_uses_native_message_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ConversationMessageService.create_feedback",
            new=AsyncMock(return_value={"result": "success"}),
        ) as feedback_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                f"/v1/messages/{uuid4()}/feedbacks",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "rating": "like", "content": "great"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    feedback_mock.assert_awaited_once()


async def test_service_api_conversations_route_uses_native_conversation_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()
    payload = {"limit": 20, "has_more": False, "data": []}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ConversationMessageService.list_conversations",
            new=AsyncMock(return_value=payload),
        ) as conversations_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/conversations",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    conversations_mock.assert_awaited_once_with(
        app_id="app-1",
        end_user=end_user,
        last_id=None,
        limit=20,
        pinned=None,
        sort_by="-updated_at",
    )


async def test_service_api_delete_conversation_route_uses_native_conversation_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ConversationMessageService.delete_conversation",
            new=AsyncMock(return_value={"result": "success"}),
        ) as delete_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.delete(
                "/v1/conversations/conversation-1",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 204
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    delete_mock.assert_awaited_once_with(
        app_id="app-1",
        conversation_id="conversation-1",
        end_user=end_user,
    )


async def test_service_api_rename_conversation_route_uses_native_conversation_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()
    payload = {
        "id": "conversation-1",
        "name": "Renamed",
        "inputs": {},
        "status": "normal",
        "introduction": None,
        "created_at": 1710000000,
        "updated_at": 1710000001,
    }

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ConversationMessageService.rename_conversation",
            new=AsyncMock(return_value=payload),
        ) as rename_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/conversations/conversation-1/name",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "name": "Renamed", "auto_generate": False},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    rename_mock.assert_awaited_once_with(
        app_id="app-1",
        conversation_id="conversation-1",
        end_user=end_user,
        name="Renamed",
        auto_generate=False,
    )


async def test_service_api_suggested_route_uses_native_suggested_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()
    runtime_context = object()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_end_user",
            new=AsyncMock(return_value=end_user),
        ) as end_user_mock,
        patch(
            "api_server.routes.service_api.ServiceApiResourceService.build_runtime_context",
            new=AsyncMock(return_value=runtime_context),
        ) as runtime_mock,
        patch(
            "api_server.routes.service_api.SuggestedQuestionsService.get_suggested_questions",
            new=AsyncMock(return_value=["next question"]),
        ) as suggested_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                f"/v1/messages/{uuid4()}/suggested",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success", "data": ["next question"]}
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    suggested_mock.assert_awaited_once()


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
