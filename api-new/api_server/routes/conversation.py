from __future__ import annotations

import uuid
from typing import Literal, TypedDict

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from api_server.errors import forbidden
from api_server.services.conversation_message import (
    ConversationItemDict,
    ConversationMessageService,
    ConversationPaginationDict,
    MessagePaginationDict,
    ResultDict,
    SavedMessagePaginationDict,
)
from api_server.services.generation_bridge import PublicGenerationBridge
from api_server.services.suggested_questions import SuggestedQuestionsService
from api_server.services.webapp_context import WebappContextService

router = APIRouter(tags=["conversation"])


class ConversationRenamePayload(BaseModel):
    name: str | None = None
    auto_generate: bool = False

    @model_validator(mode="after")
    def validate_name_requirement(self) -> "ConversationRenamePayload":
        if not self.auto_generate and (self.name is None or not self.name.strip()):
            raise ValueError("name is required when auto_generate is false")
        return self


class MessageFeedbackPayload(BaseModel):
    rating: Literal["like", "dislike"] | None = None
    content: str | None = None


class SavedMessageCreatePayload(BaseModel):
    message_id: str


class SuggestedQuestionsResponseDict(TypedDict):
    data: list[str]


@router.get("/api/conversations")
async def list_conversations(
    request: Request,
    last_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    pinned: bool | None = Query(default=None),
    sort_by: Literal["created_at", "-created_at", "updated_at", "-updated_at"] = Query(default="-updated_at"),
) -> ConversationPaginationDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    if last_id is not None:
        str(uuid.UUID(last_id))
    return await ConversationMessageService.list_conversations(
        app_id=context.app.id,
        end_user=context.end_user,
        last_id=last_id,
        limit=limit,
        pinned=pinned,
        sort_by=sort_by,
    )


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str) -> ResultDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    return await ConversationMessageService.delete_conversation(
        app_id=context.app.id,
        conversation_id=conversation_id,
        end_user=context.end_user,
    )


@router.post("/api/conversations/{conversation_id}/name")
async def rename_conversation(
    request: Request,
    conversation_id: str,
    payload: ConversationRenamePayload,
) -> ConversationItemDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    return await ConversationMessageService.rename_conversation(
        app_id=context.app.id,
        conversation_id=conversation_id,
        end_user=context.end_user,
        name=payload.name,
        auto_generate=payload.auto_generate,
    )


@router.patch("/api/conversations/{conversation_id}/pin")
async def pin_conversation(request: Request, conversation_id: str) -> ResultDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    return await ConversationMessageService.pin_conversation(
        app_id=context.app.id,
        conversation_id=conversation_id,
        end_user=context.end_user,
    )


@router.patch("/api/conversations/{conversation_id}/unpin")
async def unpin_conversation(request: Request, conversation_id: str) -> ResultDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    return await ConversationMessageService.unpin_conversation(
        app_id=context.app.id,
        conversation_id=conversation_id,
        end_user=context.end_user,
    )


@router.get("/api/messages")
async def list_messages(
    request: Request,
    conversation_id: str = Query(...),
    first_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> MessagePaginationDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    return await ConversationMessageService.list_messages(
        app_id=context.app.id,
        end_user=context.end_user,
        conversation_id=conversation_id,
        first_id=first_id,
        limit=limit,
    )


@router.post("/api/messages/{message_id}/feedbacks")
async def create_message_feedback(
    request: Request,
    message_id: str,
    payload: MessageFeedbackPayload,
) -> ResultDict:
    context = await WebappContextService.resolve(request)
    return await ConversationMessageService.create_feedback(
        app_id=context.app.id,
        message_id=message_id,
        end_user=context.end_user,
        rating=payload.rating,
        content=payload.content,
    )


@router.get("/api/messages/{message_id}/suggested-questions")
async def get_suggested_questions(request: Request, message_id: str) -> SuggestedQuestionsResponseDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    questions = await SuggestedQuestionsService.get_suggested_questions(context=context, message_id=message_id)
    return {"data": questions}


@router.get("/api/messages/{message_id}/more-like-this", response_model=None)
async def get_more_like_this(
    request: Request,
    message_id: str,
    response_mode: Literal["blocking", "streaming"] = Query(default="blocking"),
) -> JSONResponse | StreamingResponse:
    context = await WebappContextService.resolve(request)
    if context.app.mode != "completion":
        raise forbidden("not_completion_app", "Please check if your Completion app mode matches the right API route.")
    return PublicGenerationBridge.to_fastapi_response(
        await PublicGenerationBridge.run_more_like_this(
            context=context,
            message_id=message_id,
            streaming=response_mode == "streaming",
        )
    )


@router.get("/api/saved-messages")
async def list_saved_messages(
    request: Request,
    last_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> SavedMessagePaginationDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode != "completion":
        raise forbidden("not_completion_app", "Please check if your Completion app mode matches the right API route.")
    return await ConversationMessageService.list_saved_messages(
        app_id=context.app.id,
        end_user=context.end_user,
        last_id=last_id,
        limit=limit,
    )


@router.post("/api/saved-messages")
async def save_message(request: Request, payload: SavedMessageCreatePayload) -> ResultDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode != "completion":
        raise forbidden("not_completion_app", "Please check if your Completion app mode matches the right API route.")
    return await ConversationMessageService.save_message(
        app_id=context.app.id,
        message_id=payload.message_id,
        end_user=context.end_user,
    )


@router.delete("/api/saved-messages/{message_id}")
async def delete_saved_message(request: Request, message_id: str) -> ResultDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode != "completion":
        raise forbidden("not_completion_app", "Please check if your Completion app mode matches the right API route.")
    return await ConversationMessageService.delete_saved_message(
        app_id=context.app.id,
        message_id=message_id,
        end_user=context.end_user,
    )
