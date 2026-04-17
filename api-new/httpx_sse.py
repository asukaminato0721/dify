"""Minimal `httpx_sse` compatibility shim for legacy MCP imports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ServerSentEvent:
    event: str
    data: str
    id: str | None = None


class EventSource:
    _response: httpx.Response

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def iter_sse(self) -> Iterator[ServerSentEvent]:
        event_name = "message"
        data_lines: list[str] = []
        event_id: str | None = None

        for line in self._response.iter_lines():
            if line == "":
                if data_lines:
                    yield ServerSentEvent(
                        event=event_name,
                        data="\n".join(data_lines),
                        id=event_id,
                    )
                event_name = "message"
                data_lines = []
                event_id = None
                continue

            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip() or "message"
                continue
            if line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
                continue
            if line.startswith("id:"):
                event_id = line.split(":", 1)[1].strip() or None

        if data_lines:
            yield ServerSentEvent(event=event_name, data="\n".join(data_lines), id=event_id)


@contextmanager
def connect_sse(client: httpx.Client, method: str, url: str, **kwargs: object) -> Iterator[EventSource]:
    with client.stream(method, url, **kwargs) as response:
        response.raise_for_status()
        yield EventSource(response)
