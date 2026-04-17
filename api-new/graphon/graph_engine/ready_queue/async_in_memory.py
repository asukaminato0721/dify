"""Async in-memory ready queue for asyncio-based graph execution."""

from __future__ import annotations

import asyncio
import queue
from typing import final

from .protocol import ReadyQueueState


@final
class AsyncInMemoryReadyQueue:
    """Asyncio-backed ready queue used by the async graph engine path."""

    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._items: list[str] = []

    def put(self, item: str) -> None:
        self._queue.put_nowait(item)
        self._items.append(item)

    async def async_get(self, timeout: float | None = None) -> str:
        if timeout is None:
            return await self._queue.get()
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def get(self, timeout: float | None = None) -> str:
        del timeout
        try:
            item = self._queue.get_nowait()
            if item in self._items:
                self._items.remove(item)
            return item
        except asyncio.QueueEmpty as exc:
            raise queue.Empty() from exc

    def task_done(self) -> None:
        self._queue.task_done()

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()

    def dumps(self) -> str:
        return ReadyQueueState(type="AsyncInMemoryReadyQueue", version="1.0", items=list(self._items)).model_dump_json()

    def loads(self, data: str) -> None:
        state = ReadyQueueState.model_validate_json(data)
        if state.type not in {"AsyncInMemoryReadyQueue", "InMemoryReadyQueue"}:
            raise ValueError(f"Invalid serialized data type: {state.type}")
        if state.version != "1.0":
            raise ValueError(f"Unsupported version: {state.version}")
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._items = []
        for item in state.items:
            self._queue.put_nowait(item)
            self._items.append(item)
