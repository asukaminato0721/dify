from __future__ import annotations

from pathlib import Path


def _api_server_python_files() -> list[Path]:
    return sorted(Path("api_server").rglob("*.py"))


def test_fastapi_runtime_does_not_use_flask_ensure_sync() -> None:
    offenders = [
        f"{path}:{line_no}"
        for path in _api_server_python_files()
        for line_no, line in enumerate(path.read_text().splitlines(), start=1)
        if "current_app.ensure_sync(" in line
    ]
    assert offenders == []


def test_fastapi_runtime_does_not_create_sync_sessions_directly() -> None:
    offenders = [
        f"{path}:{line_no}"
        for path in _api_server_python_files()
        for line_no, line in enumerate(path.read_text().splitlines(), start=1)
        if "create_sync_session(" in line
    ]
    assert offenders == []
