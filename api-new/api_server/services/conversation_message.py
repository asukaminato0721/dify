from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import Select, delete, desc, select, update

from api_server.errors import bad_request, forbidden
from api_server.models.app import Conversation, EndUser, Message, MessageFeedback, PinnedConversation, SavedMessage
from extensions.ext_database import db


class ConversationItemDict(TypedDict):
    id: str
    name: str
    inputs: dict[str, Any]
    status: str
    introduction: str | None
    created_at: int | None
    updated_at: int | None


class ConversationPaginationDict(TypedDict):
    limit: int
    has_more: bool
    data: list[ConversationItemDict]


class MessageFeedbackDict(TypedDict):
    rating: str | None


class MessageItemDict(TypedDict):
    id: str
    conversation_id: str
    parent_message_id: str | None
    inputs: dict[str, Any]
    query: str
    answer: str
    feedback: MessageFeedbackDict | None
    retriever_resources: list[dict[str, Any]]
    created_at: int | None
    agent_thoughts: list[dict[str, Any]]
    message_files: list[dict[str, Any]]
    status: str
    error: str | None
    extra_contents: list[dict[str, Any]]
    metadata: dict[str, Any] | None


class MessagePaginationDict(TypedDict):
    limit: int
    has_more: bool
    data: list[MessageItemDict]


class SavedMessagePaginationDict(TypedDict):
    limit: int
    has_more: bool
    data: list[MessageItemDict]


class ResultDict(TypedDict):
    result: str


class ConversationMessageService:
    """Async list and mutation helpers for web conversation/message routes."""

    @staticmethod
    async def list_conversations(
        *,
        app_id: str,
        end_user: EndUser,
        last_id: str | None,
        limit: int,
        pinned: bool | None,
        sort_by: str,
    ) -> ConversationPaginationDict:
        sort_field = "updated_at" if "updated_at" in sort_by else "created_at"
        sort_desc = sort_by.startswith("-")
        order_by = desc(getattr(Conversation, sort_field)) if sort_desc else getattr(Conversation, sort_field)

        async with db.session_context() as session:
            stmt: Select[tuple[Conversation]] = select(Conversation).where(
                Conversation.is_deleted.is_(False),
                Conversation.app_id == app_id,
                Conversation.from_source == "api",
                Conversation.from_end_user_id == end_user.id,
            )

            pinned_ids: list[str] | None = None
            if pinned is not None:
                pinned_rows = await session.scalars(
                    select(PinnedConversation.conversation_id).where(
                        PinnedConversation.app_id == app_id,
                        PinnedConversation.created_by == end_user.id,
                        PinnedConversation.created_by_role == "end_user",
                    )
                )
                pinned_ids = list(pinned_rows)
                if pinned:
                    if not pinned_ids:
                        return {"limit": limit, "has_more": False, "data": []}
                    stmt = stmt.where(Conversation.id.in_(pinned_ids))
                elif pinned_ids:
                    stmt = stmt.where(~Conversation.id.in_(pinned_ids))

            if last_id:
                last_conversation = await session.scalar(
                    select(Conversation).where(Conversation.id == last_id, Conversation.app_id == app_id).limit(1)
                )
                if last_conversation is None:
                    raise bad_request("last_conversation_not_exists", "Last Conversation Not Exists.")
                marker = getattr(last_conversation, sort_field)
                if marker is not None:
                    if sort_desc:
                        stmt = stmt.where(getattr(Conversation, sort_field) < marker)
                    else:
                        stmt = stmt.where(getattr(Conversation, sort_field) > marker)

            rows = list(await session.scalars(stmt.order_by(order_by).limit(limit + 1)))

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:-1]

        return {
            "limit": limit,
            "has_more": has_more,
            "data": [ConversationMessageService._serialize_conversation(row) for row in rows],
        }

    @staticmethod
    async def rename_conversation(
        *,
        app_id: str,
        conversation_id: str,
        end_user: EndUser,
        name: str | None,
        auto_generate: bool,
    ) -> ConversationItemDict:
        async with db.session_context() as session:
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.app_id == app_id,
                    Conversation.from_source == "api",
                    Conversation.from_end_user_id == end_user.id,
                    Conversation.is_deleted.is_(False),
                ).limit(1)
            )
            if conversation is None:
                raise bad_request("conversation_not_exists", "Conversation Not Exists.")

            if auto_generate:
                first_message = await session.scalar(
                    select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.asc()).limit(1)
                )
                generated = (first_message.query[:60] if first_message else "").strip()
                conversation.name = generated or conversation.name
            else:
                conversation.name = name or conversation.name

            async with session.begin():
                session.add(conversation)

        return ConversationMessageService._serialize_conversation(conversation)

    @staticmethod
    async def delete_conversation(*, app_id: str, conversation_id: str, end_user: EndUser) -> ResultDict:
        async with db.session_context() as session:
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.app_id == app_id,
                    Conversation.from_source == "api",
                    Conversation.from_end_user_id == end_user.id,
                    Conversation.is_deleted.is_(False),
                ).limit(1)
            )
            if conversation is None:
                raise bad_request("conversation_not_exists", "Conversation Not Exists.")
            conversation.is_deleted = True
            async with session.begin():
                session.add(conversation)
        return {"result": "success"}

    @staticmethod
    async def pin_conversation(*, app_id: str, conversation_id: str, end_user: EndUser) -> ResultDict:
        async with db.session_context() as session:
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.app_id == app_id,
                    Conversation.from_end_user_id == end_user.id,
                    Conversation.is_deleted.is_(False),
                ).limit(1)
            )
            if conversation is None:
                raise bad_request("conversation_not_exists", "Conversation Not Exists.")

            existing = await session.scalar(
                select(PinnedConversation).where(
                    PinnedConversation.app_id == app_id,
                    PinnedConversation.conversation_id == conversation_id,
                    PinnedConversation.created_by == end_user.id,
                    PinnedConversation.created_by_role == "end_user",
                ).limit(1)
            )
            if existing is None:
                async with session.begin():
                    session.add(
                        PinnedConversation(
                            id=str(uuid.uuid4()),
                            app_id=app_id,
                            conversation_id=conversation_id,
                            created_by=end_user.id,
                            created_by_role="end_user",
                        )
                    )
        return {"result": "success"}

    @staticmethod
    async def unpin_conversation(*, app_id: str, conversation_id: str, end_user: EndUser) -> ResultDict:
        async with db.session_context() as session:
            async with session.begin():
                await session.execute(
                    delete(PinnedConversation).where(
                        PinnedConversation.app_id == app_id,
                        PinnedConversation.conversation_id == conversation_id,
                        PinnedConversation.created_by == end_user.id,
                        PinnedConversation.created_by_role == "end_user",
                    )
                )
        return {"result": "success"}

    @staticmethod
    async def list_messages(
        *,
        app_id: str,
        end_user: EndUser,
        conversation_id: str,
        first_id: str | None,
        limit: int,
    ) -> MessagePaginationDict:
        async with db.session_context() as session:
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.app_id == app_id,
                    Conversation.from_end_user_id == end_user.id,
                    Conversation.is_deleted.is_(False),
                ).limit(1)
            )
            if conversation is None:
                raise bad_request("conversation_not_exists", "Conversation Not Exists.")

            stmt = select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc())
            if first_id:
                first_message = await session.scalar(
                    select(Message).where(Message.id == first_id, Message.conversation_id == conversation.id).limit(1)
                )
                if first_message is None:
                    raise bad_request("first_message_not_exists", "First Message Not Exists.")
                if first_message.created_at is not None:
                    stmt = stmt.where(Message.created_at < first_message.created_at)

            rows = list(await session.scalars(stmt.limit(limit + 1)))
            message_ids = [row.id for row in rows]
            feedbacks = list(
                await session.scalars(
                    select(MessageFeedback).where(
                        MessageFeedback.message_id.in_(message_ids),
                        MessageFeedback.from_source == "user",
                        MessageFeedback.from_end_user_id == end_user.id,
                    )
                )
            ) if message_ids else []
            feedback_map = {feedback.message_id: feedback for feedback in feedbacks}

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:-1]

        return {
            "limit": limit,
            "has_more": has_more,
            "data": [ConversationMessageService._serialize_message(row, feedback_map.get(row.id)) for row in reversed(rows)],
        }

    @staticmethod
    async def create_feedback(
        *,
        app_id: str,
        message_id: str,
        end_user: EndUser,
        rating: str | None,
        content: str | None,
    ) -> ResultDict:
        async with db.session_context() as session:
            message = await session.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.app_id == app_id,
                    Message.from_source == "api",
                    Message.from_end_user_id == end_user.id,
                ).limit(1)
            )
            if message is None:
                raise bad_request("message_not_exists", "Message Not Exists.")

            feedback = await session.scalar(
                select(MessageFeedback).where(
                    MessageFeedback.message_id == message.id,
                    MessageFeedback.from_source == "user",
                    MessageFeedback.from_end_user_id == end_user.id,
                ).limit(1)
            )

            async with session.begin():
                if rating is None:
                    if feedback is not None:
                        await session.delete(feedback)
                elif feedback is None:
                    session.add(
                        MessageFeedback(
                            id=str(uuid.uuid4()),
                            app_id=app_id,
                            conversation_id=message.conversation_id,
                            message_id=message.id,
                            rating=rating,
                            from_source="user",
                            content=content,
                            from_end_user_id=end_user.id,
                        )
                    )
                else:
                    feedback.rating = rating
                    feedback.content = content
                    session.add(feedback)
        return {"result": "success"}

    @staticmethod
    async def list_saved_messages(
        *,
        app_id: str,
        end_user: EndUser,
        last_id: str | None,
        limit: int,
    ) -> SavedMessagePaginationDict:
        async with db.session_context() as session:
            saved_stmt = (
                select(SavedMessage)
                .where(
                    SavedMessage.app_id == app_id,
                    SavedMessage.created_by_role == "end_user",
                    SavedMessage.created_by == end_user.id,
                )
                .order_by(SavedMessage.created_at.desc())
            )
            saved_rows = list(await session.scalars(saved_stmt))
            message_ids = [row.message_id for row in saved_rows]
            if not message_ids:
                return {"limit": limit, "has_more": False, "data": []}

            message_stmt = select(Message).where(Message.id.in_(message_ids))
            if last_id:
                first_message = await session.scalar(select(Message).where(Message.id == last_id).limit(1))
                if first_message is None:
                    raise bad_request("last_message_not_exists", "Last Message Not Exists.")
                if first_message.created_at is not None:
                    message_stmt = message_stmt.where(Message.created_at < first_message.created_at)

            rows = list(await session.scalars(message_stmt.order_by(Message.created_at.desc()).limit(limit + 1)))
            feedbacks = list(
                await session.scalars(
                    select(MessageFeedback).where(
                        MessageFeedback.message_id.in_([row.id for row in rows]),
                        MessageFeedback.from_source == "user",
                        MessageFeedback.from_end_user_id == end_user.id,
                    )
                )
            ) if rows else []
            feedback_map = {feedback.message_id: feedback for feedback in feedbacks}

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:-1]
        return {
            "limit": limit,
            "has_more": has_more,
            "data": [ConversationMessageService._serialize_message(row, feedback_map.get(row.id)) for row in rows],
        }

    @staticmethod
    async def save_message(*, app_id: str, message_id: str, end_user: EndUser) -> ResultDict:
        async with db.session_context() as session:
            message = await session.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.app_id == app_id,
                    Message.from_source == "api",
                    Message.from_end_user_id == end_user.id,
                ).limit(1)
            )
            if message is None:
                raise bad_request("message_not_exists", "Message Not Exists.")

            existing = await session.scalar(
                select(SavedMessage).where(
                    SavedMessage.app_id == app_id,
                    SavedMessage.message_id == message_id,
                    SavedMessage.created_by_role == "end_user",
                    SavedMessage.created_by == end_user.id,
                ).limit(1)
            )
            if existing is None:
                async with session.begin():
                    session.add(
                        SavedMessage(
                            id=str(uuid.uuid4()),
                            app_id=app_id,
                            message_id=message_id,
                            created_by_role="end_user",
                            created_by=end_user.id,
                        )
                    )
        return {"result": "success"}

    @staticmethod
    async def delete_saved_message(*, app_id: str, message_id: str, end_user: EndUser) -> ResultDict:
        async with db.session_context() as session:
            async with session.begin():
                await session.execute(
                    delete(SavedMessage).where(
                        SavedMessage.app_id == app_id,
                        SavedMessage.message_id == message_id,
                        SavedMessage.created_by_role == "end_user",
                        SavedMessage.created_by == end_user.id,
                    )
                )
        return {"result": "success"}

    @staticmethod
    def _serialize_conversation(conversation: Conversation) -> ConversationItemDict:
        return {
            "id": conversation.id,
            "name": conversation.name,
            "inputs": conversation.inputs or {},
            "status": conversation.status,
            "introduction": conversation.introduction,
            "created_at": _to_timestamp(conversation.created_at),
            "updated_at": _to_timestamp(conversation.updated_at),
        }

    @staticmethod
    def _serialize_message(message: Message, feedback: MessageFeedback | None) -> MessageItemDict:
        metadata: dict[str, Any] | None = None
        if message.message_metadata:
            try:
                metadata = __import__("json").loads(message.message_metadata)
            except Exception:
                metadata = None
        return {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "parent_message_id": message.parent_message_id,
            "inputs": message.inputs or {},
            "query": message.query,
            "answer": message.answer,
            "feedback": {"rating": feedback.rating} if feedback is not None else None,
            "retriever_resources": [],
            "created_at": _to_timestamp(message.created_at),
            "agent_thoughts": [],
            "message_files": [],
            "status": message.status,
            "error": message.error,
            "extra_contents": [],
            "metadata": metadata,
        }


def _to_timestamp(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp())
