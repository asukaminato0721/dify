"""Small subset of `json_repair` used by the copied legacy modules."""

from __future__ import annotations

import json
from typing import Any


def repair_json(value: str) -> str:
    return value


def loads(value: str, **kwargs: Any) -> Any:
    return json.loads(repair_json(value), **kwargs)
