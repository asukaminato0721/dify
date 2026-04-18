from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.app.entities.queue_entities import QueueAgentThoughtEvent
from core.app.task_pipeline.easy_ui_based_generate_task_pipeline import EasyUIBasedGenerateTaskPipeline


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
