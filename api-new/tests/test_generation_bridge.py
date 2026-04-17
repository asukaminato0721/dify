from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from fastapi.responses import JSONResponse, StreamingResponse

from api_server.services.generation_bridge import (
    ChatMessagePayload,
    CompletionMessagePayload,
    PublicGenerationBridge,
    WorkflowRunPayload,
)
from core.app.entities.task_entities import CompletionAppBlockingResponse


class _AppStub:
    def __init__(self, mode: str) -> None:
        self.mode = mode


class _ContextStub:
    def __init__(self, mode: str) -> None:
        self.app = _AppStub(mode)


async def test_generation_bridge_returns_json_response_for_completion() -> None:
    context = _ContextStub("completion")
    payload = CompletionMessagePayload(inputs={}, query="hello", response_mode="blocking")
    service_response = CompletionAppBlockingResponse(
        task_id="task-1",
        data=CompletionAppBlockingResponse.Data(
            id="msg-1",
            mode="completion",
            message_id="msg-1",
            answer="hi",
            metadata={},
            created_at=1,
        ),
    )
    with patch(
        "api_server.services.generation_bridge.AsyncWebGenerationService.run_completion",
        new=AsyncMock(return_value=service_response),
    ):
        response = await PublicGenerationBridge.run_completion(context=cast(Any, context), payload=payload)

    assert isinstance(response, JSONResponse)


async def _stream() -> AsyncIterator[str]:
    yield "data: hello\n\n"


async def test_generation_bridge_returns_streaming_response_for_chat() -> None:
    context = _ContextStub("chat")
    payload = ChatMessagePayload(inputs={}, query="hello", response_mode="streaming")
    with patch(
        "api_server.services.generation_bridge.AsyncWebGenerationService.run_chat",
        new=AsyncMock(return_value=_stream()),
    ):
        response = await PublicGenerationBridge.run_chat(context=cast(Any, context), payload=payload)

    assert isinstance(response, StreamingResponse)


async def test_generation_bridge_keeps_workflow_unavailable() -> None:
    context = _ContextStub("workflow")
    payload = WorkflowRunPayload(inputs={}, response_mode="blocking")
    try:
        await PublicGenerationBridge.run_workflow(context=cast(Any, context), payload=payload)
    except Exception as exc:
        assert getattr(exc, "code", None) == "generation_backend_unavailable"
    else:
        raise AssertionError("expected workflow generation to remain unavailable")


async def test_generation_bridge_returns_json_response_for_more_like_this() -> None:
    context = _ContextStub("completion")
    service_response = CompletionAppBlockingResponse(
        task_id="task-2",
        data=CompletionAppBlockingResponse.Data(
            id="msg-2",
            mode="completion",
            message_id="msg-2",
            answer="variant",
            metadata={},
            created_at=2,
        ),
    )
    with patch(
        "api_server.services.generation_bridge.AsyncWebGenerationService.run_more_like_this",
        new=AsyncMock(return_value=service_response),
    ):
        response = await PublicGenerationBridge.run_more_like_this(
            context=cast(Any, context),
            message_id="message-1",
            streaming=False,
        )

    assert isinstance(response, JSONResponse)
