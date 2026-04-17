"""Minimal `werkzeug.wrappers` compatibility layer."""

from __future__ import annotations

from starlette.responses import Response as StarletteResponse


class Response(StarletteResponse):
    pass
