from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import relationship

from configs import dify_config
from core.db.session_factory import configure_session_factory

logger = logging.getLogger(__name__)


def _build_async_database_uri(database_uri: str) -> str:
    if database_uri.startswith("postgresql+psycopg2://"):
        return database_uri.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if database_uri.startswith("postgresql://"):
        return database_uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_uri.startswith("mysql+pymysql://"):
        return database_uri.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if database_uri.startswith("mysql://"):
        return database_uri.replace("mysql://", "mysql+aiomysql://", 1)
    return database_uri


def _normalize_async_engine_options(database_uri: str, engine_options: dict[str, Any]) -> dict[str, Any]:
    """Adapt sync SQLAlchemy engine options to async driver expectations."""

    normalized = dict(engine_options)
    connect_args = dict(normalized.get("connect_args", {}))

    if database_uri.startswith("postgresql+asyncpg://"):
        options = connect_args.pop("options", None)
        if isinstance(options, str) and options.strip():
            server_settings: dict[str, str] = {}
            option_parts = options.split()
            for index, token in enumerate(option_parts):
                if token == "-c" and index + 1 < len(option_parts):
                    key_value = option_parts[index + 1]
                    if "=" in key_value:
                        key, value = key_value.split("=", 1)
                        server_settings[key] = value
            if server_settings:
                connect_args["server_settings"] = server_settings

    normalized["connect_args"] = connect_args
    return normalized


class AsyncDatabaseManager:
    """Application-scoped async SQLAlchemy engine/session registry.

    The FastAPI runtime uses async SQLAlchemy sessions for all database access.
    Legacy sync callers must proxy through the async session factory rather than
    opening a separate sync engine/session stack.
    """

    engine: AsyncEngine | None
    session_maker: async_sessionmaker[AsyncSession] | None
    relationship = staticmethod(relationship)
    text = staticmethod(text)

    def __init__(self) -> None:
        self.engine = None
        self.session_maker = None

    def init_app(self, app: FastAPI) -> None:
        if self.engine is not None:
            return

        database_uri = _build_async_database_uri(dify_config.SQLALCHEMY_DATABASE_URI)
        engine_options = _normalize_async_engine_options(database_uri, dict(dify_config.SQLALCHEMY_ENGINE_OPTIONS))
        self.engine = create_async_engine(database_uri, **engine_options)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        configure_session_factory(self.session_maker)
        app.state.db = self

    async def dispose(self) -> None:
        if self.engine is None:
            return
        await self.engine.dispose()
        self.engine = None
        self.session_maker = None

    @asynccontextmanager
    async def session_context(self) -> AsyncIterator[AsyncSession]:
        if self.session_maker is None:
            raise RuntimeError("Database manager is not initialized.")

        async with self.session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def healthcheck(self) -> bool:
        if self.session_maker is None:
            return False

        try:
            async with self.session_maker() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.warning("Database healthcheck failed", exc_info=True)
            return False

    @property
    def session_proxy(self) -> AsyncSession:
        raise RuntimeError("Legacy db.session access is not supported in the async port.")

    @property
    def session(self) -> AsyncSession:
        raise RuntimeError("Legacy db.session access is not supported in the async port.")

db = AsyncDatabaseManager()
