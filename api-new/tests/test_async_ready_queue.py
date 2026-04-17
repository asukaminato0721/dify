from __future__ import annotations

import pytest

from graphon.graph_engine.ready_queue.async_in_memory import AsyncInMemoryReadyQueue


async def test_async_ready_queue_round_trips_items() -> None:
    queue = AsyncInMemoryReadyQueue()
    queue.put("node-1")
    queue.put("node-2")

    assert queue.qsize() == 2
    assert await queue.async_get() == "node-1"
    queue.task_done()
    assert await queue.async_get() == "node-2"
    queue.task_done()
    assert queue.empty()


def test_async_ready_queue_serialization_round_trip() -> None:
    queue = AsyncInMemoryReadyQueue()
    queue.put("node-1")
    queue.put("node-2")

    payload = queue.dumps()

    restored = AsyncInMemoryReadyQueue()
    restored.loads(payload)

    assert restored.qsize() == 2
    assert restored.get() == "node-1"
    assert restored.get() == "node-2"


def test_async_ready_queue_get_raises_queue_empty_when_no_items() -> None:
    queue = AsyncInMemoryReadyQueue()

    with pytest.raises(Exception) as exc_info:
        queue.get()

    assert exc_info.value.__class__.__name__ == "Empty"
