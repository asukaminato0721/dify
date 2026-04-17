"""Minimal stdlib `cgi` compatibility for Python 3.13."""

from __future__ import annotations

from email.message import Message


def parse_header(value: str) -> tuple[str, dict[str, str]]:
    message = Message()
    message["content-type"] = value
    main_value = message.get_content_type()
    params = {
        key: param
        for key, param in message.get_params(header="content-type", failobj=[])
        if key.lower() != main_value.lower()
    }
    params.pop("", None)
    params.pop(main_value, None)
    return main_value, params
