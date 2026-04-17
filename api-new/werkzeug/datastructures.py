"""Minimal `werkzeug.datastructures` compatibility layer."""

from __future__ import annotations

from io import BytesIO
from typing import Any


class Headers(dict[str, str]):
    pass


class FileStorage:
    filename: str | None
    name: str | None
    content_type: str | None
    mimetype: str | None
    stream: Any

    def __init__(
        self,
        stream: Any | None = None,
        filename: str | None = None,
        name: str | None = None,
        content_type: str | None = None,
    ) -> None:
        self.stream = stream if stream is not None else BytesIO()
        self.filename = filename
        self.name = name
        self.content_type = content_type
        self.mimetype = content_type

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        return self.stream.read(*args, **kwargs)
