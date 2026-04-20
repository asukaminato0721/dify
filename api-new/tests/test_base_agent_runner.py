from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import core.agent.base_agent_runner as base_agent_runner_module
from api_server.models.app import AppMode, Conversation, Message
from core.agent.base_agent_runner import BaseAgentRunner


def test_load_agent_thought_count_uses_prefetched_cache() -> None:
    runner = cast(Any, BaseAgentRunner.__new__(BaseAgentRunner))
    runner.message = Message(
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
        message_metadata=None,
        invoke_from="web-app",
        from_source="api",
        from_end_user_id="end-user-1",
        from_account_id=None,
        agent_based=False,
        workflow_run_id=None,
        app_mode=AppMode.AGENT_CHAT.value,
    )
    setattr(runner.message, "_cached_agent_thought_count", 3)

    with patch(
        "core.agent.base_agent_runner.session_factory.create_sync_session",
        side_effect=AssertionError("sync session should not be used"),
    ):
        result = runner._load_agent_thought_count()

    assert result == 3


def test_organize_agent_history_uses_prefetched_cache_without_sync_sessions() -> None:
    runner = cast(Any, BaseAgentRunner.__new__(BaseAgentRunner))
    runner.tenant_id = "tenant-1"

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
    previous_message = Message(
        id="message-prev",
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
    current_message = Message(
        id="message-current",
        app_id="app-1",
        model_provider=None,
        model_id=None,
        override_model_configs=None,
        conversation_id="conversation-1",
        inputs={},
        query="current",
        message={},
        message_tokens=0,
        message_unit_price=0,
        message_price_unit=0,
        answer="",
        answer_tokens=0,
        answer_unit_price=0,
        answer_price_unit=0,
        parent_message_id="message-prev",
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

    setattr(previous_message, "_cached_user_message_files", [])
    setattr(previous_message, "_cached_agent_thoughts", [])
    setattr(current_message, "_cached_user_message_files", [])
    setattr(current_message, "_cached_agent_thoughts", [])
    setattr(conversation, "_cached_history_messages", [current_message, previous_message])

    runner.conversation = conversation
    runner.message = current_message

    with patch(
        "core.agent.base_agent_runner.session_factory.create_sync_session",
        side_effect=AssertionError("sync session should not be used"),
    ):
        result = runner.organize_agent_history([])

    assert len(result) == 2
    assert result[0].content == "hello"
    assert result[1].content == "world"
