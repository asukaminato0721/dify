"""FastAPI public generation routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api_server.services.generation_bridge import (
    ChatMessagePayload,
    CompletionMessagePayload,
    PublicGenerationBridge,
    WorkflowRunPayload,
)
from api_server.services.webapp_context import WebappContextService

router = APIRouter(tags=["generation"])


@router.post("/api/completion-messages", response_model=None)
async def create_completion(
    request: Request,
    payload: CompletionMessagePayload,
) -> JSONResponse | StreamingResponse:
    context = await WebappContextService.resolve(request)
    return await PublicGenerationBridge.run_completion(context=context, payload=payload)


@router.post("/api/chat-messages", response_model=None)
async def create_chat_message(
    request: Request,
    payload: ChatMessagePayload,
) -> JSONResponse | StreamingResponse:
    context = await WebappContextService.resolve(request)
    return await PublicGenerationBridge.run_chat(context=context, payload=payload)


@router.post("/api/workflows/run", response_model=None)
async def run_workflow(
    request: Request,
    payload: WorkflowRunPayload,
) -> JSONResponse | StreamingResponse:
    context = await WebappContextService.resolve(request)
    return await PublicGenerationBridge.run_workflow(context=context, payload=payload)
