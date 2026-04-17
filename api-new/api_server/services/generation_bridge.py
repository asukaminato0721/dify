"""FastAPI-native validation layer for public generation endpoints.

The public generation routes remain mounted so the FastAPI surface area stays
stable, but they no longer import the legacy Flask execution stack on demand.
Authentication and request validation now stay entirely inside the FastAPI
runtime until a native generation backend is ported.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api_server.errors import forbidden, service_unavailable
from api_server.models.app import AppMode
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
    def run_completion(
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
        return cls._run(
            args=args,
            streaming=payload.response_mode == "streaming",
        )

    @classmethod
    def run_chat(
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
        return cls._run(
            args=args,
            streaming=payload.response_mode == "streaming",
        )

    @classmethod
    def run_workflow(
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
        return cls._run(
            args=payload.model_dump(exclude_none=True),
            streaming=payload.response_mode == "streaming",
        )

    @classmethod
    def _run(
        cls,
        *,
        args: dict[str, Any],
        streaming: bool,
    ) -> JSONResponse | StreamingResponse:
        del args, streaming
        raise service_unavailable(
            "generation_backend_unavailable",
            "Public generation is not ported to the FastAPI runtime yet.",
        )
