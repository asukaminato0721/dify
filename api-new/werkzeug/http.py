"""Minimal HTTP helpers required by the migration compatibility layer."""

from __future__ import annotations

from email.message import Message


def parse_options_header(value: str) -> tuple[str, dict[str, str]]:
    """Parse a header value with semi-colon parameters.

    This mirrors the part of Werkzeug used by the file-factory helpers and
    returns the main value plus a simple parameter mapping.
    """

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
