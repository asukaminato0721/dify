"""Minimal `readabilipy` compatibility shim."""

from __future__ import annotations

import re
from typing import Any


def simple_json_from_html_string(html: str, use_readability: bool = True) -> dict[str, Any]:
    del use_readability
    text = re.sub(r"<[^>]+>", " ", html)
    normalized = " ".join(text.split())
    return {
        "title": "",
        "byline": "",
        "plain_text": [normalized] if normalized else [],
    }
