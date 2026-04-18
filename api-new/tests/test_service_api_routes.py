from __future__ import annotations

from collections.abc import AsyncIterator
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


async def _stream() -> AsyncIterator[str]:
    yield "data: hi\n\n"


async def test_service_api_index_route() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/v1/")

    assert response.status_code == 200
    assert response.json()["welcome"] == "Dify OpenAPI"
    assert response.json()["api_version"] == "v1"


async def test_service_api_workspace_models_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    model_response = type(
        "ModelResponseStub",
        (),
        {"model_dump": lambda self, mode="json": {"provider": "openai", "models": []}},
    )()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ModelProviderService.get_models_by_model_type",
            return_value=[model_response],
        ) as models_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/workspaces/current/models/model-types/llm",
                headers={"Authorization": "Bearer dataset-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"data": [{"provider": "openai", "models": []}]}
    auth_mock.assert_awaited_once()
    models_mock.assert_called_once_with(tenant_id="tenant-1", model_type="llm")


async def test_service_api_dataset_metadata_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    dataset_id = str(uuid4())
    payload = {"doc_metadata": [], "built_in_field_enabled": False}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiDatasetMetadataService.get_dataset_metadata",
            new=AsyncMock(return_value=payload),
        ) as metadata_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                f"/v1/datasets/{dataset_id}/metadata",
                headers={"Authorization": "Bearer dataset-token"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    metadata_mock.assert_awaited_once_with(tenant_id="tenant-1", dataset_id=dataset_id)


async def test_service_api_dataset_built_in_metadata_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    dataset_id = str(uuid4())
    payload = {"fields": [{"name": "document_name", "type": "string"}]}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiDatasetMetadataService.get_built_in_fields",
            new=AsyncMock(return_value=payload),
        ) as metadata_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                f"/v1/datasets/{dataset_id}/metadata/built-in",
                headers={"Authorization": "Bearer dataset-token"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    metadata_mock.assert_awaited_once_with(tenant_id="tenant-1", dataset_id=dataset_id)


async def test_service_api_dataset_metadata_create_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    owner = type("OwnerStub", (), {"id": "owner-1"})()
    dataset_id = str(uuid4())
    payload = {"id": "metadata-1", "type": "string", "name": "author"}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_owner_account",
            new=AsyncMock(return_value=owner),
        ) as owner_mock,
        patch(
            "api_server.routes.service_api.ServiceApiDatasetMetadataService.create_metadata",
            new=AsyncMock(return_value=payload),
        ) as metadata_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                f"/v1/datasets/{dataset_id}/metadata",
                headers={"Authorization": "Bearer dataset-token"},
                json={"type": "string", "name": "author"},
            )

    assert response.status_code == 201
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    owner_mock.assert_awaited_once_with(tenant_id="tenant-1")
    metadata_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        dataset_id=dataset_id,
        created_by="owner-1",
        metadata_type="string",
        name="author",
    )


async def test_service_api_dataset_metadata_update_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    owner = type("OwnerStub", (), {"id": "owner-1"})()
    dataset_id = str(uuid4())
    metadata_id = str(uuid4())
    payload = {"id": metadata_id, "type": "string", "name": "author_name"}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_owner_account",
            new=AsyncMock(return_value=owner),
        ) as owner_mock,
        patch(
            "api_server.routes.service_api.ServiceApiDatasetMetadataService.update_metadata_name",
            new=AsyncMock(return_value=payload),
        ) as metadata_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.patch(
                f"/v1/datasets/{dataset_id}/metadata/{metadata_id}",
                headers={"Authorization": "Bearer dataset-token"},
                json={"name": "author_name"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    owner_mock.assert_awaited_once_with(tenant_id="tenant-1")
    metadata_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        dataset_id=dataset_id,
        metadata_id=metadata_id,
        updated_by="owner-1",
        name="author_name",
    )


async def test_service_api_dataset_metadata_delete_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    dataset_id = str(uuid4())
    metadata_id = str(uuid4())

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiDatasetMetadataService.delete_metadata",
            new=AsyncMock(return_value=None),
        ) as metadata_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.delete(
                f"/v1/datasets/{dataset_id}/metadata/{metadata_id}",
                headers={"Authorization": "Bearer dataset-token"},
            )

    assert response.status_code == 204
    auth_mock.assert_awaited_once()
    metadata_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        dataset_id=dataset_id,
        metadata_id=metadata_id,
    )


async def test_service_api_dataset_built_in_toggle_route_uses_dataset_context() -> None:
    context = type("DatasetContextStub", (), {"tenant": type("TenantStub", (), {"id": "tenant-1"})()})()
    dataset_id = str(uuid4())
    payload = {"result": "success"}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_dataset_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiDatasetMetadataService.toggle_built_in_fields",
            new=AsyncMock(return_value=payload),
        ) as metadata_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                f"/v1/datasets/{dataset_id}/metadata/built-in/enable",
                headers={"Authorization": "Bearer dataset-token"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    metadata_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        dataset_id=dataset_id,
        action="enable",
    )


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


async def test_service_api_annotation_reply_action_route_uses_native_annotation_service() -> None:
    context = _ServiceApiContextStub()
    owner = type("OwnerStub", (), {"id": "owner-1"})()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_owner_account",
            new=AsyncMock(return_value=owner),
        ) as owner_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAnnotationService.trigger_annotation_reply_action",
            return_value={"job_id": "job-1", "job_status": "waiting"},
        ) as action_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/apps/annotation-reply/enable",
                headers={"Authorization": "Bearer app-token"},
                json={
                    "score_threshold": 0.8,
                    "embedding_provider_name": "openai",
                    "embedding_model_name": "text-embedding-3-small",
                },
            )

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-1", "job_status": "waiting"}
    auth_mock.assert_awaited_once()
    owner_mock.assert_awaited_once_with(tenant_id="tenant-1")
    action_mock.assert_called_once()


async def test_service_api_annotation_reply_status_route_uses_native_annotation_service() -> None:
    context = _ServiceApiContextStub()
    job_id = str(uuid4())

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAnnotationService.get_annotation_reply_action_status",
            return_value={"job_id": job_id, "job_status": "completed", "error_msg": ""},
        ) as status_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                f"/v1/apps/annotation-reply/enable/status/{job_id}",
                headers={"Authorization": "Bearer app-token"},
            )

    assert response.status_code == 200
    assert response.json()["job_status"] == "completed"
    auth_mock.assert_awaited_once()
    status_mock.assert_called_once_with(action="enable", job_id=job_id)


async def test_service_api_annotations_list_route_uses_native_annotation_service() -> None:
    context = _ServiceApiContextStub()
    payload = {"data": [], "has_more": False, "limit": 20, "total": 0, "page": 1}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAnnotationService.list_annotations",
            new=AsyncMock(return_value=payload),
        ) as list_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/apps/annotations",
                headers={"Authorization": "Bearer app-token"},
                params={"keyword": "weather"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    list_mock.assert_awaited_once_with(app_id="app-1", page=1, limit=20, keyword="weather")


async def test_service_api_annotations_create_route_uses_native_annotation_service() -> None:
    context = _ServiceApiContextStub()
    owner = type("OwnerStub", (), {"id": "owner-1"})()
    payload = {"id": "annotation-1", "question": "q", "answer": "a", "hit_count": 0, "created_at": 1710000000}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_owner_account",
            new=AsyncMock(return_value=owner),
        ) as owner_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAnnotationService.create_annotation",
            new=AsyncMock(return_value=payload),
        ) as create_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/apps/annotations",
                headers={"Authorization": "Bearer app-token"},
                json={"question": "q", "answer": "a"},
            )

    assert response.status_code == 201
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    owner_mock.assert_awaited_once_with(tenant_id="tenant-1")
    create_mock.assert_awaited_once_with(
        app=context.app,
        account_id="owner-1",
        tenant_id="tenant-1",
        question="q",
        answer="a",
    )


async def test_service_api_annotations_update_route_uses_native_annotation_service() -> None:
    context = _ServiceApiContextStub()
    annotation_id = str(uuid4())
    payload = {"id": annotation_id, "question": "q", "answer": "a", "hit_count": 0, "created_at": 1710000000}

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAnnotationService.update_annotation",
            new=AsyncMock(return_value=payload),
        ) as update_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.put(
                f"/v1/apps/annotations/{annotation_id}",
                headers={"Authorization": "Bearer app-token"},
                json={"question": "q", "answer": "a"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    update_mock.assert_awaited_once_with(
        app=context.app,
        tenant_id="tenant-1",
        annotation_id=annotation_id,
        question="q",
        answer="a",
    )


async def test_service_api_annotations_delete_route_uses_native_annotation_service() -> None:
    context = _ServiceApiContextStub()
    annotation_id = str(uuid4())

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiAnnotationService.delete_annotation",
            new=AsyncMock(return_value=None),
        ) as delete_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.delete(
                f"/v1/apps/annotations/{annotation_id}",
                headers={"Authorization": "Bearer app-token"},
            )

    assert response.status_code == 204
    auth_mock.assert_awaited_once()
    delete_mock.assert_awaited_once_with(
        app=context.app,
        tenant_id="tenant-1",
        annotation_id=annotation_id,
    )


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


async def test_service_api_completion_route_uses_native_generation_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "completion"
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
            "api_server.routes.service_api.AsyncWebGenerationService.run_completion",
            new=AsyncMock(return_value={"answer": "hi"}),
        ) as completion_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/completion-messages",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "inputs": {}, "query": "hello"},
            )

    assert response.status_code == 200
    assert response.json() == {"answer": "hi"}
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    completion_mock.assert_awaited_once()


async def test_service_api_chat_route_uses_native_generation_service() -> None:
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
            "api_server.routes.service_api.AsyncWebGenerationService.run_chat",
            new=AsyncMock(return_value=_stream()),
        ) as chat_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/chat-messages",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "inputs": {}, "query": "hello", "response_mode": "streaming"},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    chat_mock.assert_awaited_once()


async def test_service_api_completion_stop_route_uses_task_control_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "completion"

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch("api_server.routes.service_api.TaskControlService.stop_task") as stop_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/completion-messages/task-1/stop",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    auth_mock.assert_awaited_once()
    stop_mock.assert_called_once_with("task-1")


async def test_service_api_chat_stop_route_uses_task_control_service() -> None:
    context = _ServiceApiContextStub()

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch("api_server.routes.service_api.TaskControlService.stop_task") as stop_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/chat-messages/task-1/stop",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    auth_mock.assert_awaited_once()
    stop_mock.assert_called_once_with("task-1")


async def test_service_api_workflow_route_uses_native_generation_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "workflow"
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
            "api_server.routes.service_api.AsyncWebGenerationService.run_workflow",
            new=AsyncMock(return_value={"workflow_run_id": "run-1"}),
        ) as workflow_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/workflows/run",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "inputs": {"topic": "weather"}},
            )

    assert response.status_code == 200
    assert response.json() == {"workflow_run_id": "run-1"}
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    workflow_mock.assert_awaited_once()


async def test_service_api_workflow_by_id_route_uses_native_generation_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "workflow"
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
            "api_server.routes.service_api.AsyncWebGenerationService.run_workflow",
            new=AsyncMock(return_value={"workflow_run_id": "run-2"}),
        ) as workflow_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/workflows/workflow-2/run",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "inputs": {"topic": "weather"}},
            )

    assert response.status_code == 200
    assert response.json() == {"workflow_run_id": "run-2"}
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    workflow_mock.assert_awaited_once_with(
        context=runtime_context,
        inputs={"topic": "weather"},
        files=None,
        streaming=False,
        workflow_id="workflow-2",
    )


async def test_service_api_workflow_detail_route_uses_native_workflow_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "workflow"

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiWorkflowService.get_workflow_run",
            new=AsyncMock(
                return_value={
                    "id": "run-1",
                    "workflow_id": "workflow-1",
                    "status": "succeeded",
                    "inputs": {"topic": "weather"},
                    "outputs": {"answer": "sunny"},
                    "error": None,
                    "total_steps": 3,
                    "total_tokens": 42,
                    "created_at": 1710000000,
                    "finished_at": 1710000001,
                    "elapsed_time": 1.2,
                }
            ),
        ) as detail_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/v1/workflows/run/run-1", headers={"Authorization": "Bearer app-token"})

    assert response.status_code == 200
    assert response.json()["id"] == "run-1"
    auth_mock.assert_awaited_once()
    detail_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        app_id="app-1",
        workflow_run_id="run-1",
    )


async def test_service_api_workflow_logs_route_uses_native_workflow_log_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "workflow"

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiWorkflowLogService.list_logs",
            new=AsyncMock(
                return_value={
                    "page": 1,
                    "limit": 20,
                    "total": 1,
                    "has_more": False,
                    "data": [],
                }
            ),
        ) as logs_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/workflows/logs",
                headers={"Authorization": "Bearer app-token"},
                params={"status": "succeeded"},
            )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    auth_mock.assert_awaited_once()
    logs_mock.assert_awaited_once_with(
        tenant_id="tenant-1",
        app_id="app-1",
        keyword=None,
        status="succeeded",
        created_at_before=None,
        created_at_after=None,
        page=1,
        limit=20,
        created_by_end_user_session_id=None,
        created_by_account=None,
    )


async def test_service_api_workflow_stop_route_uses_task_control_service() -> None:
    context = _ServiceApiContextStub()
    context.app.mode.value = "workflow"

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch("api_server.routes.service_api.TaskControlService.stop_task") as stop_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/workflows/tasks/task-1/stop",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == {"result": "success"}
    auth_mock.assert_awaited_once()
    stop_mock.assert_called_once_with("task-1")


async def test_service_api_feedbacks_route_uses_native_feedback_service() -> None:
    context = _ServiceApiContextStub()
    feedback_payload = {
        "data": [
            {
                "id": "feedback-1",
                "app_id": "app-1",
                "conversation_id": "conversation-1",
                "message_id": "message-1",
                "rating": "like",
                "content": "great",
                "from_source": "user",
                "from_end_user_id": "end-user-1",
                "from_account_id": None,
                "created_at": "2026-04-18T12:00:00+00:00",
                "updated_at": "2026-04-18T12:01:00+00:00",
            }
        ]
    }

    with (
        patch(
            "api_server.routes.service_api.ServiceApiAuthService.resolve_app_context",
            new=AsyncMock(return_value=context),
        ) as auth_mock,
        patch(
            "api_server.routes.service_api.ServiceApiFeedbackService.list_feedbacks",
            new=AsyncMock(return_value=feedback_payload),
        ) as feedback_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/app/feedbacks",
                headers={"Authorization": "Bearer app-token"},
                params={"page": 2, "limit": 10},
            )

    assert response.status_code == 200
    assert response.json() == feedback_payload
    auth_mock.assert_awaited_once()
    feedback_mock.assert_awaited_once_with(app_id="app-1", page=2, limit=10)


async def test_service_api_audio_to_text_route_uses_native_audio_service() -> None:
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
            "api_server.routes.service_api.PublicAudioService.transcribe_audio",
            new=AsyncMock(return_value={"text": "hello"}),
        ) as audio_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/audio-to-text",
                headers={"Authorization": "Bearer app-token"},
                files={"file": ("voice.mp3", b"data", "audio/mpeg")},
                data={"user": "session-1"},
            )

    assert response.status_code == 200
    assert response.json() == {"text": "hello"}
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    audio_mock.assert_awaited_once()


async def test_service_api_text_to_audio_route_streams_native_audio_service() -> None:
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
            "api_server.routes.service_api.PublicAudioService.synthesize_audio",
            new=AsyncMock(return_value=_stream()),
        ) as audio_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/v1/text-to-audio",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "text": "hello"},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    runtime_mock.assert_awaited_once_with(app=context.app, end_user=end_user)
    audio_mock.assert_awaited_once()


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


async def test_service_api_conversation_variables_route_uses_native_variable_service() -> None:
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
            "api_server.routes.service_api.ServiceApiConversationVariableService.list_variables",
            new=AsyncMock(return_value=payload),
        ) as variable_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                "/v1/conversations/conversation-1/variables",
                headers={"Authorization": "Bearer app-token"},
                params={"user": "session-1", "variable_name": "score"},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    variable_mock.assert_awaited_once_with(
        app=context.app,
        conversation_id="conversation-1",
        end_user=end_user,
        limit=20,
        last_id=None,
        variable_name="score",
    )


async def test_service_api_update_conversation_variable_route_uses_native_variable_service() -> None:
    context = _ServiceApiContextStub()
    end_user = object()
    payload = {
        "id": "variable-1",
        "name": "score",
        "value_type": "number",
        "value": 5,
        "description": None,
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
            "api_server.routes.service_api.ServiceApiConversationVariableService.update_variable",
            new=AsyncMock(return_value=payload),
        ) as variable_mock,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.put(
                "/v1/conversations/conversation-1/variables/variable-1",
                headers={"Authorization": "Bearer app-token"},
                json={"user": "session-1", "value": 5},
            )

    assert response.status_code == 200
    assert response.json() == payload
    auth_mock.assert_awaited_once()
    end_user_mock.assert_awaited_once_with(app=context.app, user_id="session-1")
    variable_mock.assert_awaited_once_with(
        app=context.app,
        conversation_id="conversation-1",
        variable_id="variable-1",
        end_user=end_user,
        value=5,
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
