"""FastAPI validation layer for public generation endpoints.

Authentication and request validation stay inside the FastAPI runtime. Native
completion/plain-chat execution also stays local, while workflow-backed modes
currently bridge into the copied execution stack behind the service layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api_server.errors import forbidden
from api_server.models.app import AppMode
from api_server.services.generation import AsyncWebGenerationService
from api_server.services.webapp_context import WebappContext


class CompletionMessagePayload(BaseModel):
    """Request contract for public completion generation."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="")
    files: list[dict[str, Any]] | None = Field(default=None)
    response_mode: str | None = Field(default=None)
    retriever_from: str = Field(default="web_app")

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"blocking", "streaming"}:
            raise ValueError("response_mode must be either 'blocking' or 'streaming'")
        return value


class ChatMessagePayload(BaseModel):
    """Request contract for public chat generation."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    query: str
    files: list[dict[str, Any]] | None = Field(default=None)
    response_mode: str | None = Field(default=None)
    conversation_id: str | None = Field(default=None)
    parent_message_id: str | None = Field(default=None)
    retriever_from: str = Field(default="web_app")

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"blocking", "streaming"}:
            raise ValueError("response_mode must be either 'blocking' or 'streaming'")
        return value


class WorkflowRunPayload(BaseModel):
    """Request contract for public workflow execution."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    files: list[dict[str, Any]] | None = Field(default=None)
    response_mode: str | None = Field(default=None)

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"blocking", "streaming"}:
            raise ValueError("response_mode must be either 'blocking' or 'streaming'")
        return value


class PublicGenerationBridge:
    """Validate public generation requests without importing legacy auth/runtime code."""

    @classmethod
    def ensure_mode(cls, *, app_mode: AppMode, expected_modes: set[AppMode], error_code: str, message: str) -> None:
        if app_mode not in expected_modes:
            raise forbidden(error_code, message)

    @classmethod
    async def run_completion(
        cls,
        *,
        context: WebappContext,
        payload: CompletionMessagePayload,
    ) -> JSONResponse | StreamingResponse:
        cls.ensure_mode(
            app_mode=context.app.mode,
            expected_modes={AppMode.COMPLETION},
            error_code="not_completion_app",
            message="Please check if your Completion app mode matches the right API route.",
        )
        args = payload.model_dump(exclude_none=True)
        args["auto_generate_name"] = False
        response = await AsyncWebGenerationService.run_completion(
            context=context,
            inputs=args["inputs"],
            query=args["query"],
            files=args.get("files"),
            streaming=payload.response_mode == "streaming",
        )
        return cls.to_fastapi_response(response)

    @classmethod
    async def run_chat(
        cls,
        *,
        context: WebappContext,
        payload: ChatMessagePayload,
    ) -> JSONResponse | StreamingResponse:
        cls.ensure_mode(
            app_mode=context.app.mode,
            expected_modes={AppMode.CHAT, AppMode.AGENT_CHAT, AppMode.ADVANCED_CHAT},
            error_code="not_chat_app",
            message="Please check if your app mode matches the right API route.",
        )
        args = payload.model_dump(exclude_none=True)
        args["auto_generate_name"] = False
        response = await AsyncWebGenerationService.run_chat(
            context=context,
            inputs=args["inputs"],
            query=args["query"],
            files=args.get("files"),
            conversation_id=args.get("conversation_id"),
            parent_message_id=args.get("parent_message_id"),
            streaming=payload.response_mode == "streaming",
        )
        return cls.to_fastapi_response(response)

    @classmethod
    async def run_workflow(
        cls,
        *,
        context: WebappContext,
        payload: WorkflowRunPayload,
    ) -> JSONResponse | StreamingResponse:
        cls.ensure_mode(
            app_mode=context.app.mode,
            expected_modes={AppMode.WORKFLOW},
            error_code="not_workflow_app",
            message="Please check if your Workflow app mode matches the right API route.",
        )
        response = await AsyncWebGenerationService.run_workflow(
            context=context,
            inputs=payload.inputs,
            files=payload.files,
            streaming=payload.response_mode == "streaming",
        )
        return cls.to_fastapi_response(response)

    @classmethod
    async def run_more_like_this(
        cls,
        *,
        context: WebappContext,
        message_id: str,
        streaming: bool,
    ) -> JSONResponse | StreamingResponse:
        cls.ensure_mode(
            app_mode=context.app.mode,
            expected_modes={AppMode.COMPLETION},
            error_code="not_completion_app",
            message="Please check if your Completion app mode matches the right API route.",
        )
        response = await AsyncWebGenerationService.run_more_like_this(
            context=context,
            message_id=message_id,
            streaming=streaming,
        )
        return cls.to_fastapi_response(response)

    @staticmethod
    def to_fastapi_response(response: Any) -> JSONResponse | StreamingResponse:
        if hasattr(response, "model_dump"):
            return JSONResponse(content=response.model_dump(mode="json"))
        if isinstance(response, Mapping):
            return JSONResponse(content=dict(response))
        return StreamingResponse(
            response,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
