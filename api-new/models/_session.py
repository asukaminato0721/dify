"""Session helpers for legacy model convenience accessors.

The FastAPI port uses `AsyncSession` for request handling, but a number of ORM
models still expose synchronous convenience properties. Those properties cannot
`await`, so they need an explicit compatibility path instead of touching
`db.session` or constructing `Session(db.engine)` directly from the async
engine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Executable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from core.db.session_factory import session_factory as configured_sync_session_factory

from .engine import db


@contextmanager
def legacy_sync_session() -> Iterator[Session]:
    """Yield a sync session backed by `AsyncEngine.sync_engine`.

    This is a temporary bridge for legacy model helpers that still run in sync
    contexts. New FastAPI request code should prefer `db.session_context()`
    directly.
    """

    with configured_sync_session_factory.create_session() as session:
        yield session


def with_legacy_sync_session[ReturnT](callback: Callable[[Session], ReturnT]) -> ReturnT:
    with legacy_sync_session() as session:
        return callback(session)


def legacy_scalar(statement: Executable) -> object | None:
    return with_legacy_sync_session(lambda session: session.scalar(statement))


def legacy_scalars_all(statement: Executable) -> list[object]:
    return with_legacy_sync_session(lambda session: list(session.scalars(statement).all()))


def legacy_scalar_as[ResultT](statement: Executable, expected_type: type[ResultT]) -> ResultT | None:
    result = legacy_scalar(statement)
    return result if isinstance(result, expected_type) else None


def legacy_scalars_as[ResultT](statement: Executable, expected_type: type[ResultT]) -> list[ResultT]:
    return [result for result in legacy_scalars_all(statement) if isinstance(result, expected_type)]


def legacy_get[ModelT](model_type: type[ModelT], ident: object) -> ModelT | None:
    return with_legacy_sync_session(lambda session: session.get(model_type, ident))


def legacy_session_maker() -> sessionmaker[Session]:
    return configured_sync_session_factory.get_session_maker()


async def with_async_session[ReturnT](callback: Callable[[AsyncSession], Awaitable[ReturnT]]) -> ReturnT:
    async with db.session_context() as session:
        return await callback(session)


async def async_scalar(statement: Executable) -> object | None:
    return await with_async_session(lambda session: session.scalar(statement))


async def async_scalars_all(statement: Executable) -> list[object]:
    async def load_all(session: AsyncSession) -> list[object]:
        return list((await session.scalars(statement)).all())

    return await with_async_session(load_all)


async def async_scalar_as[ResultT](statement: Executable, expected_type: type[ResultT]) -> ResultT | None:
    result = await async_scalar(statement)
    return result if isinstance(result, expected_type) else None


async def async_scalars_as[ResultT](statement: Executable, expected_type: type[ResultT]) -> list[ResultT]:
    return [result for result in await async_scalars_all(statement) if isinstance(result, expected_type)]


async def async_get[ModelT](model_type: type[ModelT], ident: object) -> ModelT | None:
    return await with_async_session(lambda session: session.get(model_type, ident))
