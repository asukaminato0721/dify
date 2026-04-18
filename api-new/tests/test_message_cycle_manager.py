from __future__ import annotations

from types import SimpleNamespace

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


def _build_manager() -> MessageCycleManager:
    application_generate_entity = SimpleNamespace(
        task_id="task-1",
        app_config=SimpleNamespace(additional_features=SimpleNamespace(show_retrieve_source=False)),
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
    original_create_session = message_cycle_manager_module.session_factory.create_session
    message_file = SimpleNamespace(message_id="message-1", belongs_to="assistant")
    message_cycle_manager_module.session_factory.create_session = lambda: _SessionStub(message_file)  # type: ignore[assignment]
    try:
        result = manager.get_message_event_type("message-1")
    finally:
        message_cycle_manager_module.session_factory.create_session = original_create_session

    assert result == StreamEvent.MESSAGE_FILE


def test_message_file_to_stream_response_uses_local_message_file_model_shape() -> None:
    manager = _build_manager()
    original_create_session = message_cycle_manager_module.session_factory.create_session
    message_file = SimpleNamespace(
        id="file-1",
        message_id="message-1",
        url="/files/tools/tool-file.png",
        type="image",
        belongs_to="assistant",
    )
    message_cycle_manager_module.session_factory.create_session = lambda: _SessionStub(message_file)  # type: ignore[assignment]
    try:
        response = manager.message_file_to_stream_response(QueueMessageFileEvent(message_file_id="file-1"))
    finally:
        message_cycle_manager_module.session_factory.create_session = original_create_session

    assert response is not None
    assert response.event == StreamEvent.MESSAGE_FILE
    assert response.id == "file-1"
    assert response.belongs_to == "assistant"
