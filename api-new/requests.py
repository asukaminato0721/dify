"""Minimal requests compatibility for optional plugin imports."""

from __future__ import annotations


class HTTPError(Exception):
    """Fallback HTTP error used by copied legacy modules."""

