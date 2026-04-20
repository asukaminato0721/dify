from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column

from core.db.session_factory import create_sync_session

from ._session import async_scalar
from .base import TypeBase
from .enums import CreatorUserRole
from .model import Message
from .types import EnumText, StringUUID


def _sync_scalar(statement: sa.Executable) -> object | None:
    with create_sync_session() as session:
        return session.scalar(statement)


class SavedMessage(TypeBase):
    __tablename__ = "saved_messages"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="saved_message_pkey"),
        sa.Index("saved_message_message_idx", "app_id", "message_id", "created_by_role", "created_by"),
        sa.Index("saved_message_message_id_idx", "message_id"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    message_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_by_role: Mapped[CreatorUserRole] = mapped_column(
        EnumText(CreatorUserRole, length=255), nullable=False, server_default=sa.text("'end_user'")
    )
    created_by: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        init=False,
    )

    @property
    def message(self) -> Message | None:
        message = _sync_scalar(select(Message).where(Message.id == self.message_id))
        return message if isinstance(message, Message) else None

    async def aload_message(self) -> Message | None:
        message = await async_scalar(select(Message).where(Message.id == self.message_id))
        return message if isinstance(message, Message) else None


class PinnedConversation(TypeBase):
    __tablename__ = "pinned_conversations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pinned_conversation_pkey"),
        sa.Index("pinned_conversation_conversation_idx", "app_id", "conversation_id", "created_by_role", "created_by"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    conversation_id: Mapped[str] = mapped_column(StringUUID)
    created_by_role: Mapped[CreatorUserRole] = mapped_column(
        EnumText(CreatorUserRole, length=255),
        nullable=False,
        server_default=sa.text("'end_user'"),
    )
    created_by: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        init=False,
    )
