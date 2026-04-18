from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from api_server.errors import ApiError
from api_server.models.app import AppMode
from api_server.services.generation import AsyncWebGenerationService


class _AppStub:
    def __init__(self, mode: AppMode) -> None:
        self.mode = mode


class _ContextStub:
    def __init__(self, mode: AppMode) -> None:
        self.app = _AppStub(mode)
        self.end_user = object()


async def test_run_chat_uses_native_runner_for_advanced_chat() -> None:
    context = _ContextStub(AppMode.ADVANCED_CHAT)
    with patch(
        "api_server.services.generation._run_native_public_advanced_chat",
        new=AsyncMock(return_value={"answer": "hi"}),
    ) as native_mock:
        response = await AsyncWebGenerationService.run_chat(
            context=cast(Any, context),
            inputs={"name": "Ada"},
            query="hello",
            files=None,
            conversation_id="conversation-1",
            parent_message_id="message-1",
            streaming=False,
        )

    assert response == {"answer": "hi"}
    native_mock.assert_awaited_once()


async def test_run_chat_uses_native_runner_for_agent_chat() -> None:
    context = _ContextStub(AppMode.AGENT_CHAT)
    with patch(
        "api_server.services.generation._run_native_public_agent_chat",
        new=AsyncMock(return_value={"answer": "hi"}),
    ) as native_mock:
        response = await AsyncWebGenerationService.run_chat(
            context=cast(Any, context),
            inputs={"name": "Ada"},
            query="hello",
            files=None,
            conversation_id="conversation-1",
            parent_message_id="message-1",
            streaming=True,
        )

    assert response == {"answer": "hi"}
    native_mock.assert_awaited_once()


async def test_run_chat_requires_streaming_for_agent_chat() -> None:
    context = _ContextStub(AppMode.AGENT_CHAT)

    with pytest.raises(ApiError) as exc_info:
        await AsyncWebGenerationService.run_chat(
            context=cast(Any, context),
            inputs={"name": "Ada"},
            query="hello",
            files=None,
            conversation_id="conversation-1",
            parent_message_id="message-1",
            streaming=False,
        )

    assert exc_info.value.code == "response_mode_required"


async def test_run_workflow_uses_compatibility_bridge() -> None:
    context = _ContextStub(AppMode.WORKFLOW)
    with patch(
        "api_server.services.generation._run_native_public_workflow",
        new=AsyncMock(return_value={"workflow_run_id": "run-1"}),
    ) as compatibility_mock:
        response = await AsyncWebGenerationService.run_workflow(
            context=cast(Any, context),
            inputs={"topic": "weather"},
            files=None,
            streaming=False,
        )

    assert response == {"workflow_run_id": "run-1"}
    compatibility_mock.assert_awaited_once()
