"""Minimal blinker compatibility shim for signal imports."""

from __future__ import annotations

from typing import Any


class _Signal:
    def connect(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def send(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def signal(_name: str) -> _Signal:
    return _Signal()
