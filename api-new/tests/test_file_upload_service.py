from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import api_server.services.file_upload as file_upload_module
from api_server.services.file_upload import FileUploadService


async def test_upload_file_offloads_filesystem_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = type("EndUserStub", (), {"tenant_id": "tenant-1", "id": "end-user-1"})()
    monkeypatch.setattr(
        file_upload_module.dify_config,
        "STORAGE_LOCAL_PATH",
        str(tmp_path),
    )

    calls: list[tuple[Callable[..., object], dict[str, object]]] = []

    async def fake_to_thread(
        func: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        calls.append((func, kwargs))
        return func(*args, **kwargs)

    class _FakeTransaction:
        async def __aenter__(self) -> _FakeTransaction:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def begin(self) -> _FakeTransaction:
            return _FakeTransaction()

        def add(self, upload_file: object) -> None:
            self.added.append(upload_file)

    class _FakeSessionContext:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def __aenter__(self) -> _FakeSession:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    fake_session = _FakeSession()

    monkeypatch.setattr(
        file_upload_module.asyncio,
        "to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(
        file_upload_module.db,
        "session_context",
        lambda: _FakeSessionContext(fake_session),
    )

    uploaded = await FileUploadService.upload_file(
        filename="hello.txt",
        content=b"hello",
        mimetype="text/plain",
        user=user,
    )

    assert uploaded["name"] == "hello.txt"
    assert uploaded["size"] == 5
    assert uploaded["extension"] == "txt"
    assert uploaded["created_by"] == "end-user-1"
    assert uploaded["url"] == f"/files/{uploaded['id']}"

    assert len(calls) == 1
    func, kwargs = calls[0]
    assert func is FileUploadService._persist_upload_file
    assert len(fake_session.added) == 1

    file_path = cast(Path, kwargs["file_path"])
    assert file_path.read_bytes() == b"hello"
    assert file_path.parent.name == "tenant-1"
    assert file_path.parent.parent.name == "upload_files"
