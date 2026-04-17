"""Minimal pypdfium2 compatibility shim."""

from __future__ import annotations


class PdfDocument:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._pages: list[object] = []

    def __iter__(self):
        return iter(self._pages)

    def __len__(self) -> int:
        return 0
