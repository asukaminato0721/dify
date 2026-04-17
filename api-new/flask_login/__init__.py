"""Minimal Flask-Login compatibility surface for the FastAPI migration."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


class UserMixin:
    """Subset of Flask-Login's user mixin used by legacy ORM models."""

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        value = getattr(self, "id", None)
        return "" if value is None else str(value)


class AnonymousUserMixin:
    @property
    def is_authenticated(self) -> bool:
        return False

    @property
    def is_active(self) -> bool:
        return False

    @property
    def is_anonymous(self) -> bool:
        return True

    def get_id(self) -> None:
        return None


class LoginManager:
    """Small compatibility shell for the legacy extension wrapper."""

    def unauthorized(self) -> Any:
        return None


class _Signal:
    def connect(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def send(self, *_args: Any, **_kwargs: Any) -> None:
        return None


user_loaded_from_request = _Signal()
user_logged_in = _Signal()

_current_user: ContextVar[Any | None] = ContextVar("compat_current_user", default=None)
current_user = _current_user.get() or AnonymousUserMixin()


def logout_user() -> None:
    _current_user.set(AnonymousUserMixin())
