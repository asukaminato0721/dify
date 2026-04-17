"""Minimal pypandoc compatibility shim."""

from __future__ import annotations


def download_pandoc() -> None:
    return None


def convert_file(*_args: object, **_kwargs: object) -> str:
    return ""


def convert_text(*_args: object, **_kwargs: object) -> str:
    return ""
