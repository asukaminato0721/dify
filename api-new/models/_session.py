"""Session helpers for legacy model convenience accessors.

The FastAPI port uses `AsyncSession` for request handling, but a number of ORM
models still expose async loader helpers that should go through the shared
database manager instead of reaching into request globals.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import Executable
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import db


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
