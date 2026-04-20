from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from api_server.models.app import App as FastAPIApp
from api_server.models.app import AppModelConfig
from api_server.models.app import Conversation
from api_server.models.app import EndUser as FastAPIEndUser
from api_server.models.app import Message
from api_server.models.app import MessageFile
from api_server.models.app import UploadFile as FastAPIUploadFile
from api_server.models.workflow import WorkflowAppLogCreatedFrom
from api_server.errors import ApiError
from api_server.models.app import AppMode
from api_server.services.generation import (
    AsyncWebGenerationService,
    _create_completion_message,
    _get_legacy_sync_session_maker,
    _prepare_native_public_agent_chat,
    _prefetch_agent_chat_memory_async,
    _save_workflow_app_log_async,
    _save_message_result,
)
from models.enums import CreatorUserRole
from graphon.file import FileTransferMethod


class _AsyncSessionStub:
    def __init__(self, *, scalar_result: object | None = None) -> None:
        self.scalar_result = scalar_result
        self.added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.refresh_calls = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, _: object) -> None:
        self.refresh_calls += 1

    async def scalar(self, *_args: object, **_kwargs: object) -> object | None:
        return self.scalar_result


class _AsyncScalarsResultStub:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


def _session_context(session: _AsyncSessionStub):
    @asynccontextmanager
    async def _manager():
        yield session

    return _manager()


class _AppStub:
    def __init__(self, mode: AppMode) -> None:
        self.mode = mode


class _ContextStub:
    def __init__(self, mode: AppMode) -> None:
        self.app = _AppStub(mode)
        self.end_user = object()


async def test_run_chat_uses_native_runner_for_advanced_chat() -> None:
    context = _ContextStub(AppMode.ADVANCED_CHAT)
    with patch(
        "api_server.services.generation._run_native_public_advanced_chat",
        new=AsyncMock(return_value={"answer": "hi"}),
    ) as native_mock:
        response = await AsyncWebGenerationService.run_chat(
            context=cast(Any, context),
            inputs={"name": "Ada"},
            query="hello",
            files=None,
            conversation_id="conversation-1",
            parent_message_id="message-1",
            streaming=False,
        )

    assert response == {"answer": "hi"}
    native_mock.assert_awaited_once()


async def test_run_chat_uses_native_runner_for_agent_chat() -> None:
    context = _ContextStub(AppMode.AGENT_CHAT)
    with patch(
        "api_server.services.generation._run_native_public_agent_chat",
        new=AsyncMock(return_value={"answer": "hi"}),
    ) as native_mock:
        response = await AsyncWebGenerationService.run_chat(
            context=cast(Any, context),
            inputs={"name": "Ada"},
            query="hello",
            files=None,
            conversation_id="conversation-1",
            parent_message_id="message-1",
            streaming=True,
        )

    assert response == {"answer": "hi"}
    native_mock.assert_awaited_once()


async def test_run_chat_requires_streaming_for_agent_chat() -> None:
    context = _ContextStub(AppMode.AGENT_CHAT)

    with pytest.raises(ApiError) as exc_info:
        await AsyncWebGenerationService.run_chat(
            context=cast(Any, context),
            inputs={"name": "Ada"},
            query="hello",
            files=None,
            conversation_id="conversation-1",
            parent_message_id="message-1",
            streaming=False,
        )

    assert exc_info.value.code == "response_mode_required"


async def test_run_workflow_uses_compatibility_bridge() -> None:
    context = _ContextStub(AppMode.WORKFLOW)
    with patch(
        "api_server.services.generation._run_native_public_workflow",
        new=AsyncMock(return_value={"workflow_run_id": "run-1"}),
    ) as compatibility_mock:
        response = await AsyncWebGenerationService.run_workflow(
            context=cast(Any, context),
            inputs={"topic": "weather"},
            files=None,
            streaming=False,
        )

    assert response == {"workflow_run_id": "run-1"}
    compatibility_mock.assert_awaited_once()


async def test_run_workflow_passes_workflow_id_override() -> None:
    context = _ContextStub(AppMode.WORKFLOW)
    with patch(
        "api_server.services.generation._run_native_public_workflow",
        new=AsyncMock(return_value={"workflow_run_id": "run-2"}),
    ) as compatibility_mock:
        response = await AsyncWebGenerationService.run_workflow(
            context=cast(Any, context),
            inputs={"topic": "weather"},
            files=None,
            streaming=False,
            workflow_id="workflow-2",
        )

    assert response == {"workflow_run_id": "run-2"}
    compatibility_mock.assert_awaited_once_with(
        context=cast(Any, context),
        inputs={"topic": "weather"},
        files=None,
        streaming=False,
        workflow_id="workflow-2",
    )


def test_get_legacy_sync_session_maker_uses_configured_factory() -> None:
    expected = object()

    with patch(
        "api_server.services.generation.configured_sync_session_factory.get_sync_session_maker",
        return_value=expected,
    ) as factory_mock:
        session_maker = _get_legacy_sync_session_maker()

    assert session_maker is expected
    factory_mock.assert_called_once_with()


async def test_create_completion_message_commits_async_session() -> None:
    session = _AsyncSessionStub()
    context = SimpleNamespace(app=SimpleNamespace(id="app-1"), end_user=SimpleNamespace(id="end-user-1"))

    with patch("api_server.services.generation.db.session_context", return_value=_session_context(session)):
        message = await _create_completion_message(
            context=cast(Any, context),
            query="hello",
            inputs={"name": "Ada"},
        )

    assert message.query == "hello"
    assert session.flush_calls == 1
    assert session.commit_calls == 1
    assert session.refresh_calls == 1


async def test_save_message_result_commits_async_session() -> None:
    message = SimpleNamespace(answer="", status="draft", message_metadata=None)
    session = _AsyncSessionStub(scalar_result=message)

    with patch("api_server.services.generation.db.session_context", return_value=_session_context(session)):
        await _save_message_result(message_id="message-1", answer="updated", usage=None)

    assert message.answer == "updated"
    assert message.status == "normal"
    assert session.flush_calls == 1
    assert session.commit_calls == 1


async def test_save_workflow_app_log_async_persists_async_log_row() -> None:
    session = _AsyncSessionStub()
    application_generate_entity = SimpleNamespace(
        app_config=SimpleNamespace(tenant_id="tenant-1", app_id="app-1"),
        invoke_from="web-app",
        workflow_execution_id="workflow-run-1",
    )
    workflow = SimpleNamespace(id="workflow-1")

    with patch("api_server.services.generation.db.session_context", return_value=_session_context(session)):
        await _save_workflow_app_log_async(
            application_generate_entity=cast(Any, application_generate_entity),
            workflow=cast(Any, workflow),
            created_by_role=CreatorUserRole.END_USER,
            created_by="end-user-1",
        )

    assert len(session.added) == 1
    workflow_app_log = session.added[0]
    assert getattr(workflow_app_log, "tenant_id") == "tenant-1"
    assert getattr(workflow_app_log, "app_id") == "app-1"
    assert getattr(workflow_app_log, "workflow_id") == "workflow-1"
    assert getattr(workflow_app_log, "workflow_run_id") == "workflow-run-1"
    assert getattr(workflow_app_log, "created_from") is WorkflowAppLogCreatedFrom.WEB_APP
    assert getattr(workflow_app_log, "created_by_role") is CreatorUserRole.END_USER
    assert getattr(workflow_app_log, "created_by") == "end-user-1"
    assert session.flush_calls == 1
    assert session.commit_calls == 1


async def test_prefetch_agent_chat_memory_attaches_message_end_file_cache() -> None:
    app = FastAPIApp(
        id="app-1",
        tenant_id="tenant-1",
        name="Agent",
        description="",
        mode=AppMode.AGENT_CHAT,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id="config-1",
        workflow_id=None,
        status="normal",
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
    app_model_config = AppModelConfig(id="config-1", app_id="app-1")
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id="config-1",
        model_provider=None,
        model_id=None,
        override_model_configs=None,
        mode=AppMode.AGENT_CHAT.value,
        name="Test",
        summary=None,
        inputs={},
        introduction=None,
        system_instruction=None,
        system_instruction_tokens=0,
        status="normal",
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        read_at=None,
        read_account_id=None,
        dialogue_count=0,
        is_deleted=False,
    )
    message = Message(
        id="message-1",
        app_id="app-1",
        model_provider=None,
        model_id=None,
        override_model_configs=None,
        conversation_id="conversation-1",
        inputs={},
        query="hello",
        message={},
        message_tokens=0,
        message_unit_price=0,
        message_price_unit=0,
        answer="",
        answer_tokens=0,
        answer_unit_price=0,
        answer_price_unit=0,
        parent_message_id=None,
        provider_response_latency=0.0,
        total_price=0,
        currency="USD",
        status="normal",
        error=None,
        message_metadata=None,
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        agent_based=False,
        workflow_run_id=None,
        app_mode=AppMode.AGENT_CHAT.value,
    )
    message_file = MessageFile(
        id="message-file-1",
        message_id="message-1",
        type="image",
        transfer_method=FileTransferMethod.LOCAL_FILE,
        belongs_to="user",
        url=None,
        upload_file_id="upload-1",
        created_by_role="end_user",
        created_by="end-user-1",
    )
    upload_file = FastAPIUploadFile(
        id="upload-1",
        tenant_id="tenant-1",
        storage_type="local",
        key="key-1",
        name="image.png",
        size=12,
        extension="png",
        mime_type="image/png",
        created_by_role="end_user",
        created_by="end-user-1",
        used=False,
        used_by=None,
        used_at=None,
        hash=None,
        source_url="",
    )
    session = SimpleNamespace(
        scalars=AsyncMock(
            side_effect=[
                _AsyncScalarsResultStub([message]),
                _AsyncScalarsResultStub([message_file]),
                _AsyncScalarsResultStub([]),
                _AsyncScalarsResultStub([upload_file]),
            ]
        )
    )

    with patch(
        "api_server.services.generation.prepare_file_dict",
        return_value={
            "related_id": "message-file-1",
            "extension": ".png",
            "filename": "image.png",
            "size": 12,
            "mime_type": "image/png",
            "transfer_method": "local_file",
            "type": "image",
            "url": "https://example.com/file",
            "upload_file_id": "upload-1",
            "remote_url": "",
        },
    ):
        await _prefetch_agent_chat_memory_async(
            session=cast(Any, session),
            conversation=conversation,
            app_model=app,
            app_model_config=app_model_config,
        )

    cached_files = getattr(message, "_cached_message_end_files", None)
    assert isinstance(cached_files, list)
    assert cached_files[0]["related_id"] == "message-file-1"
    assert cached_files[0]["upload_file_id"] == "upload-1"


async def test_prepare_native_public_agent_chat_seeds_zero_agent_thought_count() -> None:
    app = FastAPIApp(
        id="app-1",
        tenant_id="tenant-1",
        name="Agent",
        description="",
        mode=AppMode.AGENT_CHAT,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id="config-1",
        workflow_id=None,
        status="normal",
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
    app_model_config = AppModelConfig(id="config-1", app_id="app-1")
    end_user = FastAPIEndUser(
        id="end-user-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type="session",
        external_user_id=None,
        name=None,
        is_anonymous=True,
        session_id="session-1",
    )
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id="config-1",
        model_provider=None,
        model_id=None,
        override_model_configs=None,
        mode=AppMode.AGENT_CHAT.value,
        name="Test",
        summary=None,
        inputs={},
        introduction=None,
        system_instruction=None,
        system_instruction_tokens=0,
        status="normal",
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        read_at=None,
        read_account_id=None,
        dialogue_count=0,
        is_deleted=False,
    )
    message = Message(
        id="message-1",
        app_id="app-1",
        model_provider=None,
        model_id=None,
        override_model_configs=None,
        conversation_id="conversation-1",
        inputs={},
        query="hello",
        message={},
        message_tokens=0,
        message_unit_price=0,
        message_price_unit=0,
        answer="",
        answer_tokens=0,
        answer_unit_price=0,
        answer_price_unit=0,
        parent_message_id=None,
        provider_response_latency=0.0,
        total_price=0,
        currency="USD",
        status="normal",
        error=None,
        message_metadata=None,
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        agent_based=False,
        workflow_run_id=None,
        app_mode=AppMode.AGENT_CHAT.value,
    )
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[app, app_model_config, end_user]),
    )
    context = SimpleNamespace(app=app, end_user=end_user)

    with (
        patch("api_server.services.generation.db.session_context", return_value=_session_context(cast(Any, session))),
        patch(
            "api_server.services.generation._prepare_agent_chat_generation_entity",
            return_value=SimpleNamespace(app_config=SimpleNamespace(), files=[]),
        ),
        patch(
            "api_server.services.generation._init_agent_chat_records_async",
            new=AsyncMock(return_value=(conversation, message)),
        ),
        patch(
            "api_server.services.generation._prefetch_agent_chat_memory_async",
            new=AsyncMock(return_value=None),
        ),
    ):
        prepared = await _prepare_native_public_agent_chat(
            context=cast(Any, context),
            inputs={},
            query="hello",
            files=None,
            conversation_id=None,
            parent_message_id=None,
            auto_generate_name=True,
        )

    assert prepared.message is message
    assert getattr(message, "_cached_agent_thought_count") == 0
