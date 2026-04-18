from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.app.entities.task_entities import EasyUITaskState
from core.app.task_pipeline.message_cycle_manager import MessageCycleManager
from core.app.entities.queue_entities import QueueAgentThoughtEvent, QueueMessageFileEvent
from core.app.task_pipeline.easy_ui_based_generate_task_pipeline import EasyUIBasedGenerateTaskPipeline
from graphon.model_runtime.entities.llm_entities import LLMResult, LLMUsage
from graphon.model_runtime.entities.message_entities import AssistantPromptMessage


def test_agent_thought_to_stream_response_uses_event_payload_without_sync_lookup() -> None:
    pipeline = cast(Any, EasyUIBasedGenerateTaskPipeline.__new__(EasyUIBasedGenerateTaskPipeline))
    pipeline._application_generate_entity = SimpleNamespace(task_id="task-1")

    event = QueueAgentThoughtEvent(
        agent_thought_id="thought-1",
        position=2,
        thought="thinking",
        observation="observed",
        tool="search",
        tool_labels={"search": {"en_US": "Search"}},
        tool_input='{"search":"docs"}',
        message_files=["file-1"],
    )

    with patch(
        "core.app.task_pipeline.easy_ui_based_generate_task_pipeline.session_factory.create_session",
        side_effect=AssertionError("sync session should not be used"),
    ):
        response = pipeline._agent_thought_to_stream_response(event)

    assert response is not None
    assert response.id == "thought-1"
    assert response.position == 2
    assert response.tool == "search"
    assert response.message_files == ["file-1"]


def test_message_end_to_stream_response_uses_cached_files_without_sync_lookup() -> None:
    pipeline = cast(Any, EasyUIBasedGenerateTaskPipeline.__new__(EasyUIBasedGenerateTaskPipeline))
    pipeline._application_generate_entity = SimpleNamespace(task_id="task-1")
    pipeline._message_id = "message-1"
    pipeline._task_state = EasyUITaskState(
        llm_result=LLMResult(
            model="test-model",
            prompt_messages=[],
            message=AssistantPromptMessage(content="done"),
            usage=LLMUsage.empty_usage(),
        )
    )
    pipeline._message_cycle_manager = MessageCycleManager(
        application_generate_entity=SimpleNamespace(  # type: ignore[arg-type]
            task_id="task-1",
            app_config=SimpleNamespace(
                additional_features=SimpleNamespace(show_retrieve_source=False),
                app_mode="agent-chat",
                tenant_id="tenant-1",
                app_id="app-1",
            ),
            is_new_conversation=False,
            extras={},
        ),
        task_state=pipeline._task_state,
    )
    pipeline._message_cycle_manager.message_file_to_stream_response(
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

    with patch(
        "core.app.task_pipeline.easy_ui_based_generate_task_pipeline.session_factory.create_session",
        side_effect=AssertionError("sync session should not be used"),
    ):
        response = pipeline._message_end_to_stream_response()

    assert response.files is not None
    assert response.files[0]["related_id"] == "file-1"
