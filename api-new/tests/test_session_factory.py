from __future__ import annotations

from typing import Any, cast

import core.db.session_factory as session_factory_module


class _AsyncSessionStub:
    closed: bool

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _AsyncSessionMakerStub:
    session: _AsyncSessionStub
    kw: dict[str, object]

    def __init__(self) -> None:
        self.session = _AsyncSessionStub()
        self.kw = {"bind": object()}

    def __call__(self) -> _AsyncSessionStub:
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


def test_create_sync_session_wraps_async_session() -> None:
    original_async_maker = session_factory_module._async_session_maker
    session_maker = _AsyncSessionMakerStub()
    session_factory_module._async_session_maker = cast(Any, session_maker)
    try:
        with session_factory_module.create_sync_session() as session:
            assert session._ensure_session() is session_maker.session

        maker = session_factory_module.get_sync_session_maker()
        with maker() as session:
            assert session._ensure_session() is session_maker.session
    finally:
        session_factory_module._async_session_maker = original_async_maker

    assert session_maker.session.closed is True
