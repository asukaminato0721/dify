from __future__ import annotations


class Document:
    element = None
    paragraphs: list[object]
    tables: list[object]

    def __init__(self) -> None:
        self.paragraphs = []
        self.tables = []
