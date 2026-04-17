"""Minimal `werkzeug.local` compatibility helpers."""

from __future__ import annotations

from typing import Any, Callable


class LocalProxy:
    _getter: Callable[[], Any]

    def __init__(self, getter: Callable[[], Any]) -> None:
        self._getter = getter

    def _get_current_object(self) -> Any:
        return self._getter()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._getter(), name)
