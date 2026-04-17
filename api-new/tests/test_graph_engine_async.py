from __future__ import annotations

import asyncio

from graphon.graph_events.base import GraphEngineEvent
from graphon.graph_events.graph import GraphRunStartedEvent
from graphon.graph_engine.event_management.event_manager import EventManager


async def test_event_manager_emit_events_async_yields_collected_events() -> None:
    manager = EventManager()
    event = GraphRunStartedEvent()

    async def collect_once() -> GraphEngineEvent:
        async for current_event in manager.emit_events_async():
            return current_event
        raise AssertionError("expected an event")

    task = asyncio.create_task(collect_once())
    await asyncio.sleep(0)
    manager.collect(event)
    manager.mark_complete()

    result = await task
    assert result == event
