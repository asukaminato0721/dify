"""FastAPI-native feedback list helpers for the `/v1` service API slice."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import desc, select

from api_server.models.app import MessageFeedback
from extensions.ext_database import db


class ServiceApiFeedbackRecordDict(TypedDict):
    id: str
    app_id: str
    conversation_id: str
    message_id: str
    rating: str
    content: str | None
    from_source: str
    from_end_user_id: str | None
    from_account_id: str | None
    created_at: str | None
    updated_at: str | None


class ServiceApiFeedbackListResponseDict(TypedDict):
    data: list[ServiceApiFeedbackRecordDict]


class ServiceApiFeedbackService:
    """Load app-scoped feedback lists for service API routes."""

    @staticmethod
    async def list_feedbacks(*, app_id: str, page: int, limit: int) -> ServiceApiFeedbackListResponseDict:
        offset = (page - 1) * limit
        async with db.session_context() as session:
            feedbacks = (
                await session.scalars(
                    select(MessageFeedback)
                    .where(MessageFeedback.app_id == app_id)
                    .order_by(desc(MessageFeedback.created_at), desc(MessageFeedback.id))
                    .limit(limit)
                    .offset(offset)
                )
            ).all()

        return {
            "data": [
                {
                    "id": feedback.id,
                    "app_id": feedback.app_id,
                    "conversation_id": feedback.conversation_id,
                    "message_id": feedback.message_id,
                    "rating": feedback.rating,
                    "content": feedback.content,
                    "from_source": feedback.from_source,
                    "from_end_user_id": feedback.from_end_user_id,
                    "from_account_id": feedback.from_account_id,
                    "created_at": feedback.created_at.isoformat() if feedback.created_at is not None else None,
                    "updated_at": feedback.updated_at.isoformat() if feedback.updated_at is not None else None,
                }
                for feedback in feedbacks
            ]
        }
