from __future__ import annotations

import json
from typing import Any, cast

import api_server.models.app as app_models
from api_server.models.app import AppMode, AppModelConfig, Conversation, Message, MessageAgentThought


def test_local_conversation_model_config_uses_app_model_config_when_no_override() -> None:
    app_model_config = AppModelConfig(
        id="config-1",
        app_id="app-1",
        opening_statement="Hello",
        model=json.dumps({"provider": "openai", "name": "gpt-4o-mini", "mode": "chat", "completion_params": {}}),
        file_upload=json.dumps({"enabled": False}),
        agent_mode=json.dumps({"enabled": False, "tools": [], "strategy": "router"}),
        dataset_configs=json.dumps({"retrieval_model": "multiple"}),
        sensitive_word_avoidance=json.dumps({"enabled": False, "type": "", "config": {}}),
        text_to_speech=json.dumps({"enabled": False}),
        speech_to_text=json.dumps({"enabled": False}),
        suggested_questions_after_answer=json.dumps({"enabled": False}),
        retriever_resource=json.dumps({"enabled": True}),
    )
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id="config-1",
        model_provider="openai",
        model_id="gpt-4o-mini",
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

    original_create_session = app_models.configured_sync_session_factory.create_session

    class _SessionStub:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _stmt):
            return app_model_config

    app_models.configured_sync_session_factory.create_session = cast(Any, lambda: _SessionStub())
    try:
        result = conversation.model_config
    finally:
        app_models.configured_sync_session_factory.create_session = original_create_session

    assert result["provider"] == "openai"
    assert result["model_id"] == "gpt-4o-mini"
    assert result["model"]["provider"] == "openai"


def test_local_conversation_model_config_uses_override_when_present() -> None:
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id=None,
        model_provider="openai",
        model_id="gpt-4.1",
        override_model_configs=json.dumps({"model": {"provider": "openai", "name": "gpt-4.1"}}),
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

    result = conversation.model_config

    assert result["provider"] == "openai"
    assert result["model_id"] == "gpt-4.1"
    assert result["model"]["name"] == "gpt-4.1"


def test_local_message_metadata_dict_matches_legacy_shape() -> None:
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
        answer="world",
        answer_tokens=0,
        answer_unit_price=0,
        answer_price_unit=0,
        parent_message_id=None,
        provider_response_latency=0.0,
        total_price=0,
        currency="USD",
        status="normal",
        error=None,
        message_metadata=json.dumps({"retriever_resources": []}),
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        agent_based=False,
        workflow_run_id=None,
        app_mode=AppMode.AGENT_CHAT.value,
    )

    assert message.message_metadata_dict == {"retriever_resources": []}


def test_local_message_agent_thought_helpers_match_legacy_shape() -> None:
    thought = MessageAgentThought(
        id="thought-1",
        message_id="message-1",
        position=1,
        created_by_role="end_user",
        created_by="end-user-1",
        message_chain_id=None,
        thought="thinking",
        tool="search;lookup",
        tool_labels_str=json.dumps({"search": {"en_US": "Search"}}),
        tool_meta_str="{}",
        tool_input=None,
        observation=None,
        tool_process_data=None,
        message=None,
        message_token=None,
        message_unit_price=None,
        message_price_unit=None,
        message_files=json.dumps(["file-1"]),
        answer=None,
        answer_token=None,
        answer_unit_price=None,
        answer_price_unit=None,
        tokens=None,
        total_price=None,
        currency=None,
        latency=None,
    )

    assert thought.files == ["file-1"]
    assert thought.tool_labels == {"search": {"en_US": "Search"}}


def test_local_conversation_app_prefers_prefetched_app() -> None:
    app = app_models.App(
        id="app-1",
        tenant_id="tenant-1",
        name="Demo",
        description="",
        mode=AppMode.AGENT_CHAT,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id=None,
        workflow_id=None,
        status=app_models.AppStatus.NORMAL,
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id=None,
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

    setattr(conversation, "_cached_app", app)

    original_create_session = app_models.configured_sync_session_factory.create_session
    app_models.configured_sync_session_factory.create_session = cast(Any, lambda: (_ for _ in ()).throw(AssertionError))
    try:
        result = conversation.app
    finally:
        app_models.configured_sync_session_factory.create_session = original_create_session

    assert result is app


def test_local_conversation_model_config_prefers_prefetched_config() -> None:
    app_model_config = AppModelConfig(
        id="config-1",
        app_id="app-1",
        opening_statement="Hello",
        model=json.dumps({"provider": "openai", "name": "gpt-4o-mini", "mode": "chat", "completion_params": {}}),
        file_upload=json.dumps({"enabled": False}),
        agent_mode=json.dumps({"enabled": False, "tools": [], "strategy": "router"}),
        dataset_configs=json.dumps({"retrieval_model": "multiple"}),
        sensitive_word_avoidance=json.dumps({"enabled": False, "type": "", "config": {}}),
        text_to_speech=json.dumps({"enabled": False}),
        speech_to_text=json.dumps({"enabled": False}),
        suggested_questions_after_answer=json.dumps({"enabled": False}),
        retriever_resource=json.dumps({"enabled": True}),
    )
    conversation = Conversation(
        id="conversation-1",
        app_id="app-1",
        app_model_config_id="config-1",
        model_provider="openai",
        model_id="gpt-4o-mini",
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

    setattr(conversation, "_cached_app_model_config", app_model_config)

    original_create_session = app_models.configured_sync_session_factory.create_session
    app_models.configured_sync_session_factory.create_session = cast(Any, lambda: (_ for _ in ()).throw(AssertionError))
    try:
        result = conversation.model_config
    finally:
        app_models.configured_sync_session_factory.create_session = original_create_session

    assert result["provider"] == "openai"
    assert result["model_id"] == "gpt-4o-mini"
    assert result["model"]["provider"] == "openai"
