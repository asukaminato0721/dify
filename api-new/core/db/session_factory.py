"""Global SQLAlchemy session factory registry.

`api-new` request code should consume async SQLAlchemy sessions from this
module. The copied sync-first workflow and model seams still need a temporary
compatibility path, but that path must stay explicit so new code does not
accidentally reopen sync sessions inside async execution.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

_async_session_maker: async_sessionmaker[AsyncSession] | None = None
_sync_session_maker: sessionmaker[Session] | None = None


def configure_session_factory(
    session_source: AsyncEngine | async_sessionmaker[AsyncSession], expire_on_commit: bool = False
) -> None:
    """Configure the global async session factory used by FastAPI request code."""

    global _async_session_maker

    if isinstance(session_source, AsyncEngine):
        _async_session_maker = async_sessionmaker(bind=session_source, expire_on_commit=expire_on_commit)
        return

    _async_session_maker = session_source


def configure_sync_session_factory(engine: Engine, expire_on_commit: bool = False) -> None:
    """Configure the legacy sync session factory for copied compatibility seams."""

    global _sync_session_maker
    _sync_session_maker = sessionmaker(bind=engine, expire_on_commit=expire_on_commit)


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    if _async_session_maker is None:
        raise RuntimeError("Async session factory not configured. Call configure_session_factory() first.")
    return _async_session_maker


def get_sync_session_maker() -> sessionmaker[Session]:
    if _sync_session_maker is None:
        raise RuntimeError("Sync session factory not configured. Call configure_sync_session_factory() first.")
    return _sync_session_maker


def create_session() -> AsyncSession:
    return get_session_maker()()


def create_sync_session() -> Session:
    return get_sync_session_maker()()


class SessionFactory:
    @staticmethod
    def configure(session_source: AsyncEngine | async_sessionmaker[AsyncSession], expire_on_commit: bool = False) -> None:
        configure_session_factory(session_source, expire_on_commit)

    @staticmethod
    def configure_sync(engine: Engine, expire_on_commit: bool = False) -> None:
        configure_sync_session_factory(engine, expire_on_commit)

    @staticmethod
    def get_session_maker() -> async_sessionmaker[AsyncSession]:
        return get_session_maker()

    @staticmethod
    def get_sync_session_maker() -> sessionmaker[Session]:
        return get_sync_session_maker()

    @staticmethod
    def create_session() -> AsyncSession:
        return create_session()

    @staticmethod
    def create_sync_session() -> Session:
        return create_sync_session()


session_factory = SessionFactory()
