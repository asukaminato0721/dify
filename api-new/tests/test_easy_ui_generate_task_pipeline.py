from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from api_server.models.app import Conversation, Message
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
        "core.app.task_pipeline.easy_ui_based_generate_task_pipeline.session_factory.create_sync_session",
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
        "core.app.task_pipeline.easy_ui_based_generate_task_pipeline.session_factory.create_sync_session",
        side_effect=AssertionError("sync session should not be used"),
    ):
        response = pipeline._message_end_to_stream_response()

    assert response.files is not None
    assert response.files[0]["related_id"] == "file-1"


def test_pipeline_init_seeds_prefetched_message_end_files_without_sync_lookup() -> None:
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
        app_mode="agent-chat",
    )
    setattr(
        message,
        "_cached_message_end_files",
        [
            {
                "related_id": "file-1",
                "extension": ".png",
                "filename": "image.png",
                "size": 12,
                "mime_type": "image/png",
                "transfer_method": "local_file",
                "type": "image",
                "url": "https://example.com/file",
                "upload_file_id": "upload-1",
                "remote_url": "",
            }
        ],
    )

    pipeline = EasyUIBasedGenerateTaskPipeline(
        application_generate_entity=cast(
            Any,
                SimpleNamespace(
                    task_id="task-1",
                    model_conf=SimpleNamespace(mode="chat", model="test-model"),
                    app_config=SimpleNamespace(
                        app_mode="agent-chat",
                        app_model_config_dict={},
                    sensitive_word_avoidance=None,
                ),
                trace_manager=None,
            ),
        ),
        queue_manager=cast(Any, SimpleNamespace()),
        conversation=Conversation(
            id="conversation-1",
            app_id="app-1",
            app_model_config_id=None,
            model_provider=None,
            model_id=None,
            override_model_configs=None,
            mode="agent-chat",
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
        ),
        message=message,
        stream=True,
    )
    pipeline._task_state = EasyUITaskState(
        llm_result=LLMResult(
            model="test-model",
            prompt_messages=[],
            message=AssistantPromptMessage(content="done"),
            usage=LLMUsage.empty_usage(),
        )
    )

    with patch(
        "core.app.task_pipeline.easy_ui_based_generate_task_pipeline.session_factory.create_sync_session",
        side_effect=AssertionError("sync session should not be used"),
    ):
        response = pipeline._message_end_to_stream_response()

    assert response.files is not None
    assert response.files[0]["related_id"] == "file-1"


class _SessionUpdateStub:
    def __init__(self) -> None:
        self.executed: list[object] = []

    def scalar(self, _stmt: object) -> object:
        raise AssertionError("session.scalar should not be used")

    def execute(self, stmt: object) -> None:
        self.executed.append(stmt)


def test_save_message_uses_cached_message_without_sync_reload() -> None:
    pipeline = cast(Any, EasyUIBasedGenerateTaskPipeline.__new__(EasyUIBasedGenerateTaskPipeline))
    pipeline._message_id = "message-1"
    pipeline._conversation_id = "conversation-1"
    pipeline._model_config = SimpleNamespace(mode="chat")
    pipeline._application_generate_entity = SimpleNamespace(task_id="task-1")
    pipeline._task_state = EasyUITaskState(
        llm_result=LLMResult(
            model="test-model",
            prompt_messages=[],
            message=AssistantPromptMessage(content="done"),
            usage=LLMUsage.empty_usage(),
        )
    )
    pipeline._message = Message(
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
        app_mode="chat",
    )
    pipeline.start_at = 0.0

    session = _SessionUpdateStub()
    with patch(
        "core.app.task_pipeline.easy_ui_based_generate_task_pipeline.PromptMessageUtil.prompt_messages_to_prompt_for_saving",
        return_value={},
    ):
        pipeline._save_message(session=session, trace_manager=None)

    assert pipeline._message.answer == "done"
    assert len(session.executed) == 1
