from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from core.app.apps.advanced_chat.generate_task_pipeline import AdvancedChatAppGenerateTaskPipeline
from api_server.models.app import EndUser
from core.app.apps.common.workflow_response_converter import WorkflowResponseConverter
from core.app.entities.app_invoke_entities import WorkflowAppGenerateEntity
from core.app.entities.app_invoke_entities import InvokeFrom
from core.app.entities.queue_entities import QueueHumanInputFormFilledEvent
from core.app.entities.queue_entities import QueueWorkflowPausedEvent
from core.app.entities.task_entities import HumanInputRequiredResponse, WorkflowPauseStreamResponse
from graphon.entities import WorkflowStartReason
from graphon.entities.pause_reason import HumanInputRequired
from graphon.nodes.human_input.entities import HumanInputNodeData, UserAction
from graphon.nodes.human_input.enums import HumanInputFormStatus
from graphon.nodes.human_input.human_input_node import HumanInputNode


@dataclass
class _GenerateEntityStub:
    inputs: dict[str, object]
    invoke_from: InvokeFrom


@dataclass
class _GraphRuntimeStateStub:
    total_tokens: int
    node_run_steps: int


@dataclass
class _FormEntityStub:
    id: str
    rendered_content: str
    expiration_time: datetime
    display_in_ui: bool
    preferred_access_token: str | None
    selected_action_id: str | None = None
    submitted_data: dict[str, object] | None = None
    submitted: bool = False
    status: HumanInputFormStatus = HumanInputFormStatus.WAITING


def test_human_input_required_event_carries_pause_metadata() -> None:
    node = object.__new__(HumanInputNode)
    node._node_data = HumanInputNodeData(  # type: ignore[attr-defined]
        title="Review request",
        user_actions=[UserAction(id="approve", title="Approve")],
    )
    node.id = "node-1"  # type: ignore[assignment]
    node.resolve_default_values = lambda: {"name": "Ada"}  # type: ignore[method-assign]

    expiration_time = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)
    event = node._human_input_required_event(  # type: ignore[attr-defined]
        _FormEntityStub(
            id="form-1",
            rendered_content="Please approve",
            expiration_time=expiration_time,
            display_in_ui=True,
            preferred_access_token="form-token",
        )
    )

    assert event.form_id == "form-1"
    assert event.node_id == "node-1"
    assert event.display_in_ui is True
    assert event.form_token == "form-token"
    assert event.expiration_time == expiration_time
    assert event.resolved_default_values == {"name": "Ada"}


def test_workflow_pause_to_stream_response_uses_reason_metadata() -> None:
    converter = WorkflowResponseConverter(
        application_generate_entity=cast(
            WorkflowAppGenerateEntity,
            _GenerateEntityStub(inputs={}, invoke_from=InvokeFrom.WEB_APP),
        ),
        user=EndUser(
            id="end-user-1",
            tenant_id="tenant-1",
            app_id="app-1",
            type="session",
            external_user_id=None,
            name=None,
            is_anonymous=True,
            session_id="session-1",
        ),
        system_variables=[],
    )
    converter.workflow_start_to_stream_response(
        task_id="task-1",
        workflow_run_id="run-1",
        workflow_id="workflow-1",
        reason=WorkflowStartReason.INITIAL,
    )

    expiration_time = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)
    responses = converter.workflow_pause_to_stream_response(
        event=QueueWorkflowPausedEvent(
            reasons=[
                HumanInputRequired(
                    form_id="form-1",
                    form_content="Please approve",
                    node_id="node-1",
                    node_title="Review request",
                    inputs=[],
                    actions=[],
                    expiration_time=expiration_time,
                    display_in_ui=True,
                    form_token="form-token",
                )
            ],
            outputs={},
            paused_nodes=["node-1"],
        ),
        task_id="task-1",
        graph_runtime_state=_GraphRuntimeStateStub(total_tokens=12, node_run_steps=3),  # type: ignore[arg-type]
    )

    assert len(responses) == 2

    human_input_response = responses[0]
    assert isinstance(human_input_response, HumanInputRequiredResponse)
    assert human_input_response.data.form_id == "form-1"
    assert human_input_response.data.form_token == "form-token"
    assert human_input_response.data.display_in_ui is True
    assert human_input_response.data.expiration_time == int(expiration_time.timestamp())

    pause_response = responses[1]
    assert isinstance(pause_response, WorkflowPauseStreamResponse)
    assert pause_response.data.paused_nodes == ["node-1"]
    assert pause_response.data.total_tokens == 12
    assert pause_response.data.total_steps == 3


def test_advanced_chat_human_input_filled_event_uses_event_form_id() -> None:
    pipeline = cast(AdvancedChatAppGenerateTaskPipeline, AdvancedChatAppGenerateTaskPipeline.__new__(AdvancedChatAppGenerateTaskPipeline))
    pipeline._application_generate_entity = cast(Any, _GenerateEntityStub(inputs={}, invoke_from=InvokeFrom.WEB_APP))
    setattr(pipeline._application_generate_entity, "task_id", "task-1")
    calls: list[tuple[str | None, str | None]] = []
    pipeline._persist_human_input_extra_content = lambda *, node_id=None, form_id=None: calls.append((node_id, form_id))  # type: ignore[method-assign]
    pipeline._workflow_response_converter = cast(
        Any,
        type(
            "_ConverterStub",
            (),
            {
                "human_input_form_filled_to_stream_response": staticmethod(
                    lambda *, event, task_id: {"event_form_id": event.form_id, "task_id": task_id}
                )
            },
        )(),
    )

    responses = list(
        pipeline._handle_human_input_form_filled_event(
            QueueHumanInputFormFilledEvent(
                node_execution_id="node-exec-1",
                form_id="form-1",
                node_id="node-1",
                node_type="human_input",
                node_title="Review request",
                rendered_content="Approved",
                action_id="approve",
                action_text="Approve",
            )
        )
    )

    assert calls == [("node-1", "form-1")]
    assert responses == [{"event_form_id": "form-1", "task_id": "task-1"}]
