from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar, cast

import click
from fastapi import FastAPI

from configs import dify_config
from flask import _current_app_var

_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])


class _ConfigProxy(dict[str, Any]):
    """Expose config values through both mapping and attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - compatibility fallback
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class DifyApp(FastAPI):
    """FastAPI application with the minimal Flask-like surface still in use.

    The async port still has a handful of legacy helpers and Celery/task
    adapters that expect `app_context()`, `extensions`, and `cli`. Keep that
    compatibility surface here so those callers can keep moving toward native
    FastAPI code without depending on Flask itself.
    """

    config: _ConfigProxy
    extensions: dict[str, Any]
    cli: click.Group
    secret_key: str | None
    json: Any
    name: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.name = "Dify API"
        self.extensions = cast(dict[str, Any], getattr(self.state, "extensions", {}))
        self.state.extensions = self.extensions
        self.cli = click.Group()
        self.secret_key = dify_config.SECRET_KEY
        self.json = None
        self.config = _ConfigProxy(root_path=str(Path(__file__).resolve().parent), SECRET_KEY=dify_config.SECRET_KEY)
        for key, value in dify_config.model_dump().items():
            self.config[key] = value

    @contextmanager
    def app_context(self) -> Iterator["DifyApp"]:
        token = _current_app_var.set(cast(Any, self))
        try:
            yield self
        finally:
            _current_app_var.reset(token)

    def ensure_sync(self, func: _CallableT) -> _CallableT:
        if not inspect.iscoroutinefunction(func):
            return func

        def _runner(*args: Any, **kwargs: Any) -> Any:
            return asyncio.run(func(*args, **kwargs))

        return cast(_CallableT, _runner)

    def after_request(self, func: _CallableT) -> _CallableT:
        handlers = cast(list[Callable[..., Any]], getattr(self.state, "after_request_handlers", []))
        handlers.append(func)
        self.state.after_request_handlers = handlers
        return func

    def register_blueprint(self, blueprint: Any) -> None:
        blueprints = cast(list[Any], getattr(self.state, "blueprints", []))
        blueprints.append(blueprint)
        self.state.blueprints = blueprints
