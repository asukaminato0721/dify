"""Minimal pandas compatibility shim for optional import paths.

This is intentionally tiny and only supports the subset of APIs touched by
lightweight utility code in the migration workspace.
"""

from __future__ import annotations

import csv
from typing import Any, Iterator


class _ILocAccessor:
    _row: "Series"

    def __init__(self, row: "Series") -> None:
        self._row = row

    def __getitem__(self, index: int) -> str | None:
        try:
            return self._row._values[index]
        except IndexError as exc:
            raise IndexError(index) from exc


class Series:
    _data: dict[str, str | None]
    _values: list[str | None]
    iloc: _ILocAccessor

    def __init__(self, data: dict[str, str | None], values: list[str | None]) -> None:
        self._data = data
        self._values = values
        self.iloc = _ILocAccessor(self)

    def items(self):
        return self._data.items()

    def __getitem__(self, key: str) -> str | None:
        return self._data[key]


class DataFrame:
    _rows: list[Series]
    columns: list[str]

    def __init__(self, columns: list[str], rows: list[list[str | None]]) -> None:
        self.columns = columns
        self._rows = [
            Series(dict(zip(columns, row, strict=False)), row)
            for row in rows
        ]

    def iterrows(self) -> Iterator[tuple[int, Series]]:
        for index, row in enumerate(self._rows):
            yield index, row

    def dropna(self, *, how: str = "any", inplace: bool = False) -> "DataFrame | None":
        del how
        filtered_rows = [row for row in self._rows if any(value not in (None, "") for value in row._values)]
        if inplace:
            self._rows = filtered_rows
            return None
        return DataFrame(self.columns, [row._values for row in filtered_rows])

    def __len__(self) -> int:
        return len(self._rows)


class ExcelFile:
    sheet_names: list[str]

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.sheet_names = []

    def parse(self, *args: Any, **kwargs: Any) -> DataFrame:
        del args, kwargs
        return DataFrame([], [])


def read_csv(
    file_obj: Any,
    *,
    dtype: object | None = None,
    nrows: int | None = None,
    engine: str | None = None,
    on_bad_lines: str | None = None,
    **_kwargs: Any,
) -> DataFrame:
    del dtype, engine, on_bad_lines
    reader = csv.reader(file_obj)
    rows = list(reader)
    if not rows:
        return DataFrame([], [])
    header = [str(item) for item in rows[0]]
    data_rows = [[item for item in row] for row in rows[1 : None if nrows is None else nrows + 1]]
    return DataFrame(header, data_rows)


def notna(value: Any) -> bool:
    return value is not None and value == value
