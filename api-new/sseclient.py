"""Minimal `sseclient` compatibility shim."""

from __future__ import annotations

from collections.abc import Iterator


class SSEClient:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __iter__(self) -> Iterator[object]:
        return iter(())
