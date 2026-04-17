"""Minimal Flask compatibility shim for the FastAPI migration.

This module only implements the subset of Flask APIs that the remaining
legacy runtime imports need during the port. It is intentionally small and
explicit so the active dependency set stays Flask-free.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from starlette.responses import Response as StarletteResponse
from starlette.responses import StreamingResponse


_current_app_var: ContextVar["Flask | None"] = ContextVar("compat_current_app", default=None)
_request_var: ContextVar[Any | None] = ContextVar("compat_request", default=None)
_g_var: ContextVar[SimpleNamespace] = ContextVar("compat_g", default=SimpleNamespace())


class _Proxy:
    def __init__(self, getter: Callable[[], Any]):
        self._getter = getter

    def _get_current_object(self) -> Any:
        return self._getter()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._getter(), name)


class _Signal:
    def connect(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def send(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class Blueprint:
    def __init__(self, name: str, import_name: str, url_prefix: str | None = None):
        self.name = name
        self.import_name = import_name
        self.url_prefix = url_prefix


class Flask:
    config: dict[str, Any]
    extensions: dict[str, Any]

    def __init__(self, import_name: str):
        self.import_name = import_name
        self.config = {}
        self.extensions = {}

    @contextmanager
    def app_context(self) -> Iterator["Flask"]:
        token = _current_app_var.set(self)
        try:
            yield self
        finally:
            _current_app_var.reset(token)

    def _get_current_object(self) -> "Flask":
        return self


def _get_current_app() -> Flask:
    app = _current_app_var.get()
    if app is None:
        raise RuntimeError("No current app available in Flask compatibility shim.")
    return app


def _get_request() -> Any:
    request = _request_var.get()
    if request is None:
        raise RuntimeError("No request available in Flask compatibility shim.")
    return request


def _get_g() -> SimpleNamespace:
    return _g_var.get()


current_app = _Proxy(_get_current_app)
request = _Proxy(_get_request)
g = _Proxy(_get_g)
got_request_exception = _Signal()


def has_request_context() -> bool:
    return _request_var.get() is not None


def copy_current_request_context(func: Callable[..., Any]) -> Callable[..., Any]:
    return func


def stream_with_context(response: Any) -> Any:
    return response


def render_template(_template_name: str, **context: Any) -> str:
    return "".join(str(value) for value in context.values())


def render_template_string(template: str, **context: Any) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
    return rendered


class Response(StarletteResponse):
    def __new__(
        cls,
        response: Any = None,
        status: int = 200,
        headers: dict[str, str] | None = None,
        mimetype: str | None = None,
        content_type: str | None = None,
        direct_passthrough: bool = False,
    ) -> StarletteResponse:
        media_type = content_type or mimetype
        if isinstance(response, (bytes, str)) or response is None:
            return StarletteResponse(
                content=response or b"",
                status_code=status,
                headers=headers,
                media_type=media_type,
            )
        if isinstance(response, Iterable):
            return StreamingResponse(
                content=response,
                status_code=status,
                headers=headers,
                media_type=media_type,
            )
        return StarletteResponse(content=response, status_code=status, headers=headers, media_type=media_type)


def make_response(data: Any) -> Any:
    return data
