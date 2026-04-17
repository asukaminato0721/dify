"""Minimal Werkzeug compatibility package for the FastAPI port.

This local package only exposes the tiny subset of Werkzeug APIs that the
remaining legacy modules import while the Flask stack is being ported away.
"""

from . import exceptions


class Request:
    pass


__all__ = ["Request", "exceptions"]
