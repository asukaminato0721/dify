from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from api_server.errors import ApiError
from api_server.models.app import AppMode
from api_server.services.generation import (
    AsyncWebGenerationService,
    _create_completion_message,
    _get_legacy_sync_session_maker,
    _save_message_result,
)


class _AsyncSessionStub:
    def __init__(self, *, scalar_result: object | None = None) -> None:
        self.scalar_result = scalar_result
        self.added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.refresh_calls = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, _: object) -> None:
        self.refresh_calls += 1

    async def scalar(self, *_args: object, **_kwargs: object) -> object | None:
        return self.scalar_result


def _session_context(session: _AsyncSessionStub):
    @asynccontextmanager
    async def _manager():
        yield session

    return _manager()


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


async def test_run_workflow_passes_workflow_id_override() -> None:
    context = _ContextStub(AppMode.WORKFLOW)
    with patch(
        "api_server.services.generation._run_native_public_workflow",
        new=AsyncMock(return_value={"workflow_run_id": "run-2"}),
    ) as compatibility_mock:
        response = await AsyncWebGenerationService.run_workflow(
            context=cast(Any, context),
            inputs={"topic": "weather"},
            files=None,
            streaming=False,
            workflow_id="workflow-2",
        )

    assert response == {"workflow_run_id": "run-2"}
    compatibility_mock.assert_awaited_once_with(
        context=cast(Any, context),
        inputs={"topic": "weather"},
        files=None,
        streaming=False,
        workflow_id="workflow-2",
    )


def test_get_legacy_sync_session_maker_uses_configured_factory() -> None:
    expected = object()

    with patch(
        "api_server.services.generation.configured_sync_session_factory.get_session_maker",
        return_value=expected,
    ) as factory_mock:
        session_maker = _get_legacy_sync_session_maker()

    assert session_maker is expected
    factory_mock.assert_called_once_with()


async def test_create_completion_message_commits_async_session() -> None:
    session = _AsyncSessionStub()
    context = SimpleNamespace(app=SimpleNamespace(id="app-1"), end_user=SimpleNamespace(id="end-user-1"))

    with patch("api_server.services.generation.db.session_context", return_value=_session_context(session)):
        message = await _create_completion_message(
            context=cast(Any, context),
            query="hello",
            inputs={"name": "Ada"},
        )

    assert message.query == "hello"
    assert session.flush_calls == 1
    assert session.commit_calls == 1
    assert session.refresh_calls == 1


async def test_save_message_result_commits_async_session() -> None:
    message = SimpleNamespace(answer="", status="draft", message_metadata=None)
    session = _AsyncSessionStub(scalar_result=message)

    with patch("api_server.services.generation.db.session_context", return_value=_session_context(session)):
        await _save_message_result(message_id="message-1", answer="updated", usage=None)

    assert message.answer == "updated"
    assert message.status == "normal"
    assert session.flush_calls == 1
    assert session.commit_calls == 1
