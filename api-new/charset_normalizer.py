"""Small fallback shim for `charset_normalizer`.

This keeps optional text-extraction and HTTP helper modules importable in the
FastAPI migration workspace without requiring the third-party package on the
active runtime path.
"""

from __future__ import annotations

from pathlib import Path


class CharsetMatch:
    encoding: str | None
    coherence: float
    language: str | None

    def __init__(self, encoding: str | None) -> None:
        self.encoding = encoding
        self.coherence = 0.0
        self.language = None


class CharsetMatches:
    _matches: list[CharsetMatch]

    def __init__(self, matches: list[CharsetMatch]) -> None:
        self._matches = matches

    def best(self) -> CharsetMatch | None:
        return self._matches[0] if self._matches else None


def _detect_encoding(data: bytes) -> str | None:
    for encoding in ("utf-8", "latin-1"):
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return None


def from_bytes(data: bytes, cp_isolation: list[str] | None = None) -> CharsetMatches:
    del cp_isolation
    return CharsetMatches([CharsetMatch(_detect_encoding(data))])


def from_path(path: str) -> CharsetMatches:
    return from_bytes(Path(path).read_bytes())
