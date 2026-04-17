from __future__ import annotations


class Table:
    rows: list[object]

    def __init__(self) -> None:
        self.rows = []
