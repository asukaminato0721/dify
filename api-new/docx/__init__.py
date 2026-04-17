"""Minimal python-docx compatibility shim."""

from __future__ import annotations

from .document import Document as _Document


def Document(*_args: object, **_kwargs: object) -> _Document:
    return _Document()
