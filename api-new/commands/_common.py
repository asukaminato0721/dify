"""Shared CLI helpers for the incremental FastAPI command port."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import click


def unsupported_command(command_name: str) -> click.Command:
    """Return a placeholder command until the legacy CLI is ported."""

    @click.command(command_name)
    def _command() -> None:
        raise click.ClickException(f"`{command_name}` is not ported in api-new yet.")

    return cast(click.Command, _command)


def unsupported_with_options(command_name: str, *decorators: Callable[[Callable[..., Any]], Callable[..., Any]]) -> click.Command:
    """Build a placeholder command while preserving the legacy CLI signature."""

    @click.command(command_name)
    def _command(**_: Any) -> None:
        raise click.ClickException(f"`{command_name}` is not ported in api-new yet.")

    wrapped = cast(Callable[..., Any], _command)
    for decorator in decorators:
        wrapped = decorator(wrapped)
    return cast(click.Command, wrapped)
