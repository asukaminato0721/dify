from __future__ import annotations

from typing import Any, cast

import core.db.session_factory as session_factory_module


class _AsyncSessionStub:
    pass


class _AsyncSessionMakerStub:
    session: _AsyncSessionStub

    def __init__(self) -> None:
        self.session = _AsyncSessionStub()

    def __call__(self) -> _AsyncSessionStub:
        return self.session


class _SyncSessionStub:
    pass


class _SyncSessionMakerStub:
    session: _SyncSessionStub

    def __init__(self) -> None:
        self.session = _SyncSessionStub()

    def __call__(self) -> _SyncSessionStub:
        return self.session


def test_create_session_uses_async_factory() -> None:
    original_async_maker = session_factory_module._async_session_maker
    session_maker = _AsyncSessionMakerStub()
    session_factory_module._async_session_maker = cast(Any, session_maker)
    try:
        assert session_factory_module.create_session() is session_maker.session
        assert session_factory_module.session_factory.create_session() is session_maker.session
    finally:
        session_factory_module._async_session_maker = original_async_maker


def test_create_sync_session_uses_legacy_sync_factory() -> None:
    original_sync_maker = session_factory_module._sync_session_maker
    session_maker = _SyncSessionMakerStub()
    session_factory_module._sync_session_maker = cast(Any, session_maker)
    try:
        assert session_factory_module.create_sync_session() is session_maker.session
        assert session_factory_module.session_factory.create_sync_session() is session_maker.session
    finally:
        session_factory_module._sync_session_maker = original_sync_maker
