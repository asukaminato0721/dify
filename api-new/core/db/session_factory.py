"""Global async SQLAlchemy session registry plus sync-boundary adapters.

The repo's database access should use `AsyncSession` directly. A subset of
legacy sync entrypoints still needs a synchronous interface while their call
chains are being ported, so this module exposes adapter objects that proxy sync
method calls onto the configured async session maker without reopening a sync
engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import Future
from threading import Thread
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def _run_awaitable_sync[ResultT](awaitable: Coroutine[Any, Any, ResultT]) -> ResultT:
    """Run an awaitable from sync code without requiring callers to manage loops."""

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


class SyncSessionAdapter:
    """Synchronous facade over `AsyncSession` for legacy boundary code."""

    _session_maker: async_sessionmaker[AsyncSession]
    _session: AsyncSession | None

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker
        self._session = None

    def _ensure_session(self) -> AsyncSession:
        if self._session is None:
            self._session = self._session_maker()
        return self._session

    def __enter__(self) -> SyncSessionAdapter:
        self._ensure_session()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        session = self._session
        self._session = None
        if session is None:
            return False
        if exc_type is not None:
            _run_awaitable_sync(session.rollback())
        _run_awaitable_sync(session.close())
        return False

    def begin(self) -> _SyncTransactionAdapter:
        return _SyncTransactionAdapter(self)

    @property
    def no_autoflush(self) -> Any:
        return self._ensure_session().no_autoflush

    def get_bind(self) -> AsyncEngine | None:
        bind = self._session_maker.kw.get("bind")
        return bind if isinstance(bind, AsyncEngine) else None

    def add(self, instance: object, _warn: bool = True) -> None:
        self._ensure_session().add(instance, _warn=_warn)

    def add_all(self, instances: list[object]) -> None:
        self._ensure_session().add_all(instances)

    def merge(self, instance: object, *, load: bool = True, options: object | None = None) -> object:
        session = cast(Any, self._ensure_session())
        return _run_awaitable_sync(session.merge(instance, load=load, options=options))

    def delete(self, instance: object) -> None:
        _run_awaitable_sync(self._ensure_session().delete(instance))

    def flush(self, objects: list[object] | None = None) -> None:
        _run_awaitable_sync(self._ensure_session().flush(objects))

    def refresh(
        self,
        instance: object,
        attribute_names: list[str] | None = None,
        with_for_update: object | None = None,
    ) -> None:
        session = cast(Any, self._ensure_session())
        _run_awaitable_sync(session.refresh(instance, attribute_names, with_for_update))

    def rollback(self) -> None:
        _run_awaitable_sync(self._ensure_session().rollback())

    def commit(self) -> None:
        _run_awaitable_sync(self._ensure_session().commit())

    def close(self) -> None:
        _run_awaitable_sync(self._ensure_session().close())
        self._session = None

    def expire_all(self) -> None:
        self._ensure_session().expire_all()

    def execute(self, statement: object, params: object | None = None, **kwargs: object) -> Any:
        session = cast(Any, self._ensure_session())
        return _run_awaitable_sync(session.execute(statement, params=params, **kwargs))

    def scalar(self, statement: object, params: object | None = None, **kwargs: object) -> Any:
        session = cast(Any, self._ensure_session())
        return _run_awaitable_sync(session.scalar(statement, params=params, **kwargs))

    def scalars(self, statement: object, params: object | None = None, **kwargs: object) -> Any:
        session = cast(Any, self._ensure_session())
        return _run_awaitable_sync(session.scalars(statement, params=params, **kwargs))

    def get(
        self,
        entity: object,
        ident: object,
        *,
        options: object | None = None,
        populate_existing: bool = False,
        with_for_update: object | None = None,
        identity_token: object | None = None,
        execution_options: object | None = None,
    ) -> Any:
        session = cast(Any, self._ensure_session())
        return _run_awaitable_sync(
            session.get(
                entity,
                ident,
                options=options,
                populate_existing=populate_existing,
                with_for_update=with_for_update,
                identity_token=identity_token,
                execution_options=execution_options,
            )
        )


class _SyncTransactionAdapter:
    _session_adapter: SyncSessionAdapter
    _transaction: Any | None

    def __init__(self, session_adapter: SyncSessionAdapter) -> None:
        self._session_adapter = session_adapter
        self._transaction = None

    def __enter__(self) -> SyncSessionAdapter:
        self._transaction = self._session_adapter._ensure_session().begin()
        _run_awaitable_sync(self._transaction.__aenter__())
        return self._session_adapter

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        transaction = self._transaction
        self._transaction = None
        if transaction is None:
            return False
        _run_awaitable_sync(transaction.__aexit__(exc_type, exc, tb))
        return False


class SyncSessionMakerAdapter:
    """Callable/begin-able proxy matching the small sessionmaker surface used in the repo."""

    _session_maker: async_sessionmaker[AsyncSession]
    kw: dict[str, object]

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker
        self.kw = {"bind": session_maker.kw.get("bind")}

    def __call__(self, *_args: object, **_kwargs: object) -> SyncSessionAdapter:
        return SyncSessionAdapter(self._session_maker)

    def begin(self) -> _SyncSessionMakerBeginAdapter:
        return _SyncSessionMakerBeginAdapter(self._session_maker)


class _SyncSessionMakerBeginAdapter:
    _session: SyncSessionAdapter | None
    _session_maker: async_sessionmaker[AsyncSession]
    _transaction: _SyncTransactionAdapter | None

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session = None
        self._session_maker = session_maker
        self._transaction = None

    def __enter__(self) -> SyncSessionAdapter:
        session = SyncSessionAdapter(self._session_maker)
        session.__enter__()
        transaction = session.begin()
        transaction.__enter__()
        self._session = session
        self._transaction = transaction
        return session

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        session = self._session
        transaction = self._transaction
        self._session = None
        self._transaction = None
        if session is None:
            return False
        if transaction is not None:
            transaction.__exit__(exc_type, exc, tb)
        session.__exit__(exc_type, exc, tb)
        return False


def configure_session_factory(
    session_source: AsyncEngine | async_sessionmaker[AsyncSession], expire_on_commit: bool = False
) -> None:
    """Configure the global async session factory used by request code and sync adapters."""

    global _async_session_maker

    if isinstance(session_source, AsyncEngine):
        _async_session_maker = async_sessionmaker(bind=session_source, expire_on_commit=expire_on_commit)
        return

    _async_session_maker = session_source


def configure_sync_session_factory(_engine: object, expire_on_commit: bool = False) -> None:
    """Backward-compatible no-op while sync callers are migrated off the old API."""

    _ = expire_on_commit


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    if _async_session_maker is None:
        raise RuntimeError("Async session factory not configured. Call configure_session_factory() first.")
    return _async_session_maker


def get_sync_session_maker() -> SyncSessionMakerAdapter:
    return SyncSessionMakerAdapter(get_session_maker())


def create_session() -> AsyncSession:
    return get_session_maker()()


def create_sync_session() -> SyncSessionAdapter:
    return SyncSessionAdapter(get_session_maker())


class SessionFactory:
    @staticmethod
    def configure(session_source: AsyncEngine | async_sessionmaker[AsyncSession], expire_on_commit: bool = False) -> None:
        configure_session_factory(session_source, expire_on_commit)

    @staticmethod
    def configure_sync(engine: object, expire_on_commit: bool = False) -> None:
        configure_sync_session_factory(engine, expire_on_commit)

    @staticmethod
    def get_session_maker() -> async_sessionmaker[AsyncSession]:
        return get_session_maker()

    @staticmethod
    def get_sync_session_maker() -> SyncSessionMakerAdapter:
        return get_sync_session_maker()

    @staticmethod
    def create_session() -> AsyncSession:
        return create_session()

    @staticmethod
    def create_sync_session() -> SyncSessionAdapter:
        return create_sync_session()


session_factory = SessionFactory()
