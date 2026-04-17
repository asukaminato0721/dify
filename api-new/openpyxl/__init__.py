"""Minimal openpyxl compatibility shim."""

from __future__ import annotations


class _Workbook:
    sheetnames: list[str]

    def __init__(self) -> None:
        self.sheetnames = []

    def __getitem__(self, key: str):
        raise KeyError(key)

    def close(self) -> None:
        return None


def load_workbook(*_args: object, **_kwargs: object) -> _Workbook:
    return _Workbook()
