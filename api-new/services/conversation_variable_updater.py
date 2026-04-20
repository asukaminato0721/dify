"""Persistence helper for conversation-scoped workflow variables.

The legacy workflow runtime still invokes this helper synchronously from graph
layers, but the active FastAPI path now injects an async session maker. Keep
the public `update()` method synchronous for the graph engine while routing the
actual database write through whichever SQLAlchemy session factory was provided.
"""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import Future
from threading import Thread

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graphon.variables.variables import VariableBase
from api_server.models.app import ConversationVariable as FastAPIConversationVariable
from models import ConversationVariable


class ConversationVariableNotFoundError(Exception):
    pass


def _run_awaitable_sync[ResultT](awaitable: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    future: Future[ResultT] = Future()

    def _runner() -> None:
        try:
            future.set_result(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - defensive propagation
            future.set_exception(exc)

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    return future.result()


class ConversationVariableUpdater:
    def __init__(self, session_maker: sessionmaker[Session] | async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker

    def update(self, conversation_id: str, variable: VariableBase) -> None:
        if isinstance(self._session_maker, async_sessionmaker):
            _run_awaitable_sync(self._aupdate(conversation_id=conversation_id, variable=variable))
            return

        stmt = select(ConversationVariable).where(
            ConversationVariable.id == variable.id,
            ConversationVariable.conversation_id == conversation_id,
        )
        with self._session_maker() as session:
            row = session.scalar(stmt)
            if not row:
                raise ConversationVariableNotFoundError("conversation variable not found in the database")
            row.data = variable.model_dump_json()
            session.commit()

    async def _aupdate(self, *, conversation_id: str, variable: VariableBase) -> None:
        stmt = select(FastAPIConversationVariable).where(
            FastAPIConversationVariable.id == variable.id,
            FastAPIConversationVariable.conversation_id == conversation_id,
        )
        async with self._session_maker() as session:
            row = await session.scalar(stmt)
            if not row:
                raise ConversationVariableNotFoundError("conversation variable not found in the database")
            row.data = variable.model_dump_json()
            await session.commit()

    def flush(self) -> None:
        pass
