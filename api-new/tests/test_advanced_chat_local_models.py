from __future__ import annotations

import json
from datetime import datetime

from api_server.models.app import App, AppMode, AppModelConfig, Conversation, ConversationVariable, Message, Workflow
from core.app.apps.advanced_chat.generate_task_pipeline import ConversationSnapshot, MessageSnapshot, WorkflowSnapshot
from graphon.variables.variables import StringVariable


def test_local_app_model_config_exposes_legacy_dict_shape() -> None:
    config = AppModelConfig(
        id="config-1",
        app_id="app-1",
        opening_statement="Hello",
        suggested_questions=json.dumps(["What can you do?"]),
    )

    result = config.to_dict()

    assert result["opening_statement"] == "Hello"
    assert result["suggested_questions"] == ["What can you do?"]


def test_local_workflow_variable_helpers_decode_runtime_variables() -> None:
    environment_variable = StringVariable(
        id="env-1",
        name="api_key",
        value="secret",
        selector=["env", "api_key"],
    )
    conversation_variable = StringVariable(
        id="conv-1",
        name="topic",
        value="weather",
        selector=["conversation", "topic"],
    )
    workflow = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type="chat",
        version="draft",
        graph=json.dumps({"nodes": []}),
        features=json.dumps({}),
        created_by="account-1",
        environment_variables=json.dumps({"api_key": environment_variable.model_dump(mode="json")}),
        conversation_variables=json.dumps({"topic": conversation_variable.model_dump(mode="json")}),
    )

    assert workflow.environment_variables_value_objects[0].name == "api_key"
    assert workflow.conversation_variables_value_objects[0].name == "topic"


def test_local_conversation_variable_round_trip_matches_legacy_shape() -> None:
    variable = StringVariable(
        id="conv-1",
        name="topic",
        value="weather",
        selector=["conversation", "topic"],
    )

    conversation_variable = ConversationVariable.from_variable(
        app_id="app-1",
        conversation_id="conversation-1",
        variable=variable,
    )

    restored = conversation_variable.to_variable()

    assert restored.id == variable.id
    assert restored.name == variable.name
    assert restored.value == variable.value


def test_advanced_chat_snapshots_accept_local_models() -> None:
    workflow = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type="chat",
        version="draft",
        graph=json.dumps({"nodes": []}),
        features=json.dumps({"text_to_speech": {"enabled": False}}),
        created_by="account-1",
    )
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id=None,
        mode=AppMode.ADVANCED_CHAT.value,
        name="Test",
        inputs={},
        introduction=None,
        status="normal",
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        is_deleted=False,
    )
    message = Message(
        id="message-1",
        app_id="app-1",
        conversation_id="conversation-1",
        inputs={},
        query="hello",
        answer="world",
        status="paused",
        error=None,
        message_metadata=None,
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        created_at=datetime(2026, 4, 18, 12, 0, 0),
    )

    workflow_snapshot = WorkflowSnapshot.from_workflow(workflow)
    conversation_snapshot = ConversationSnapshot.from_conversation(conversation)
    message_snapshot = MessageSnapshot.from_message(message)

    assert workflow_snapshot.id == "workflow-1"
    assert conversation_snapshot.mode == AppMode.ADVANCED_CHAT.value
    assert message_snapshot.status == "paused"
