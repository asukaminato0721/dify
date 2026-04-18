from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import core.app.task_pipeline.message_cycle_manager as message_cycle_manager_module
from core.app.entities.queue_entities import QueueMessageFileEvent
from core.app.entities.task_entities import EasyUITaskState, StreamEvent
from core.app.task_pipeline.message_cycle_manager import MessageCycleManager
from graphon.model_runtime.entities.llm_entities import LLMResult, LLMUsage
from graphon.model_runtime.entities.message_entities import AssistantPromptMessage


class _SessionStub:
    def __init__(self, scalar_result: object | None) -> None:
        self._scalar_result = scalar_result

    def __enter__(self) -> "_SessionStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def scalar(self, _stmt: object) -> object | None:
        return self._scalar_result


class _SessionMakerStub:
    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> "_SessionMakerStub":
        return self

    def __enter__(self) -> "_SessionMakerStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, stmt: object) -> None:
        self.executed.append(stmt)


def _build_manager() -> MessageCycleManager:
    application_generate_entity = SimpleNamespace(
        task_id="task-1",
        app_config=SimpleNamespace(
            additional_features=SimpleNamespace(show_retrieve_source=False),
            app_mode="agent-chat",
            tenant_id="tenant-1",
            app_id="app-1",
        ),
        is_new_conversation=False,
        extras={},
    )
    return MessageCycleManager(
        application_generate_entity=application_generate_entity,  # type: ignore[arg-type]
        task_state=EasyUITaskState(
            llm_result=LLMResult(
                model="test-model",
                prompt_messages=[],
                message=AssistantPromptMessage(content=""),
                usage=LLMUsage.empty_usage(),
            )
        ),
    )


def test_get_message_event_type_uses_local_message_file_presence() -> None:
    manager = _build_manager()
    response = manager.message_file_to_stream_response(
        QueueMessageFileEvent(
            message_file_id="file-1",
            message_id="message-1",
            url="/files/tools/tool-file.png",
            type="image",
            belongs_to="assistant",
        )
    )
    assert response is not None

    result = manager.get_message_event_type("message-1")

    assert result == StreamEvent.MESSAGE_FILE


def test_message_file_to_stream_response_uses_event_payload_without_sync_session() -> None:
    manager = _build_manager()
    original_create_session = message_cycle_manager_module.session_factory.create_session
    message_cycle_manager_module.session_factory.create_session = lambda: (_ for _ in ()).throw(
        AssertionError("sync session should not be used")
    )  # type: ignore[assignment]
    try:
        response = manager.message_file_to_stream_response(
            QueueMessageFileEvent(
                message_file_id="file-1",
                message_id="message-1",
                url="/files/tools/tool-file.png",
                type="image",
                belongs_to="assistant",
            )
        )
    finally:
        message_cycle_manager_module.session_factory.create_session = original_create_session

    assert response is not None
    assert response.event == StreamEvent.MESSAGE_FILE
    assert response.id == "file-1"
    assert response.belongs_to == "assistant"


def test_message_file_to_stream_response_falls_back_to_sync_lookup_when_event_is_id_only() -> None:
    manager = _build_manager()
    original_create_session = message_cycle_manager_module.session_factory.create_session
    message_file = SimpleNamespace(
        id="file-1",
        message_id="message-1",
        url="/files/tools/tool-file.png",
        type="image",
        belongs_to="assistant",
        transfer_method="tool_file",
        upload_file_id="upload-1",
    )
    message_cycle_manager_module.session_factory.create_session = lambda: _SessionStub(message_file)  # type: ignore[assignment]
    try:
        response = manager.message_file_to_stream_response(QueueMessageFileEvent(message_file_id="file-1"))
    finally:
        message_cycle_manager_module.session_factory.create_session = original_create_session

    assert response is not None
    assert response.id == "file-1"


def test_message_file_to_stream_response_caches_message_end_files() -> None:
    manager = _build_manager()

    response = manager.message_file_to_stream_response(
        QueueMessageFileEvent(
            message_file_id="file-1",
            message_id="message-1",
            url="/files/tools/tool-file.png",
            type="image",
            belongs_to="assistant",
            transfer_method="tool_file",
            upload_file_id="upload-1",
        )
    )

    assert response is not None
    cached_files = manager.get_cached_message_end_files("message-1")
    assert cached_files is not None
    assert cached_files[0]["related_id"] == "file-1"
    assert cached_files[0]["type"] == "image"


def test_generate_conversation_name_worker_uses_app_config_directly() -> None:
    manager = _build_manager()
    session_maker = _SessionMakerStub()

    with (
        patch.object(message_cycle_manager_module.session_factory, "get_session_maker", return_value=session_maker),
        patch.object(message_cycle_manager_module.redis_client, "get", return_value=None),
        patch.object(message_cycle_manager_module.redis_client, "setex") as setex_mock,
        patch.object(
            message_cycle_manager_module.LLMGenerator,
            "generate_conversation_name",
            return_value="generated-name",
        ) as generate_mock,
    ):
        manager._generate_conversation_name_worker("conversation-1", "hello")

    generate_mock.assert_called_once_with("tenant-1", "hello", "conversation-1", "app-1")
    setex_mock.assert_called_once()
    assert len(session_maker.executed) == 1
