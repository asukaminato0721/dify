from __future__ import annotations

import json
from typing import Any, cast

import core.memory.token_buffer_memory as token_buffer_memory_module
from api_server.models.app import App, AppMode, AppModelConfig, AppStatus, Conversation, Message
from core.memory.token_buffer_memory import TokenBufferMemory


class _ModelInstanceStub:
    def get_llm_num_tokens(self, _prompt_messages: object) -> int:
        return 0


def test_token_buffer_memory_uses_prefetched_history_without_sync_sessions() -> None:
    app = App(
        id="app-1",
        tenant_id="tenant-1",
        name="Demo",
        description="",
        mode=AppMode.AGENT_CHAT,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id="config-1",
        workflow_id=None,
        status=AppStatus.NORMAL,
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
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
    message = Message(
        id="message-1",
        app_id="app-1",
        model_provider="openai",
        model_id="gpt-4o-mini",
        override_model_configs=None,
        conversation_id="conversation-1",
        inputs={},
        query="hello",
        message={},
        message_tokens=0,
        message_unit_price=0,
        message_price_unit=0,
        answer="world",
        answer_tokens=1,
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

    setattr(conversation, "_cached_app", app)
    setattr(conversation, "_cached_app_model_config", app_model_config)
    setattr(conversation, "_cached_history_messages", [message])
    setattr(message, "_cached_user_message_files", [])
    setattr(message, "_cached_assistant_message_files", [])

    original_create_session = token_buffer_memory_module.session_factory.create_session
    token_buffer_memory_module.session_factory.create_session = cast(
        Any, lambda: (_ for _ in ()).throw(AssertionError("sync session should not be used"))
    )
    try:
        prompt_messages = TokenBufferMemory(
            conversation=conversation,
            model_instance=cast(Any, _ModelInstanceStub()),
        ).get_history_prompt_messages()
    finally:
        token_buffer_memory_module.session_factory.create_session = original_create_session

    assert len(prompt_messages) == 2
    assert prompt_messages[0].content == "hello"
    assert prompt_messages[1].content == "world"
