"""Async dispatcher for graph execution events."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, final

from graphon.graph_events.base import GraphNodeEventBase
from graphon.graph_events.node import NodeRunExceptionEvent, NodeRunFailedEvent, NodeRunSucceededEvent

from ..event_management import EventManager
from ..worker_management.async_worker_pool import AsyncWorkerPool

if TYPE_CHECKING:
    from ..event_management import EventHandler
    from ..graph_state_manager import GraphStateManager
    from ..domain.graph_execution import GraphExecution
    from ..command_processing import CommandProcessor


@final
class AsyncDispatcher:
    _COMMAND_TRIGGER_EVENTS = (
        NodeRunSucceededEvent,
        NodeRunFailedEvent,
        NodeRunExceptionEvent,
    )

    def __init__(
        self,
        *,
        event_queue: asyncio.Queue[GraphNodeEventBase],
        event_handler: "EventHandler",
        state_manager: "GraphStateManager",
        graph_execution: "GraphExecution",
        command_processor: "CommandProcessor",
        worker_pool: AsyncWorkerPool,
        event_emitter: EventManager | None = None,
    ) -> None:
        self._event_queue = event_queue
        self._event_handler = event_handler
        self._state_manager = state_manager
        self._graph_execution = graph_execution
        self._command_processor = command_processor
        self._worker_pool = worker_pool
        self._event_emitter = event_emitter

    async def run(self) -> None:
        try:
            self._process_commands()
            paused = False
            while True:
                if self._graph_execution.aborted or self._state_manager.is_execution_complete():
                    break
                if self._graph_execution.is_paused:
                    paused = True
                    break

                try:
                    event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                    self._event_handler.dispatch(event)
                    self._event_queue.task_done()
                    self._process_commands(event)
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.1)

            self._process_commands()
            if paused:
                await self._drain_events_until_idle()
            else:
                await self._drain_event_queue()
        finally:
            if not self._graph_execution.is_paused and not self._graph_execution.completed:
                self._graph_execution.complete()
            if self._event_emitter:
                self._event_emitter.mark_complete()

    def _process_commands(self, event: GraphNodeEventBase | None = None) -> None:
        if event is None or isinstance(event, self._COMMAND_TRIGGER_EVENTS):
            self._command_processor.process_commands()

    async def _drain_event_queue(self) -> None:
        while True:
            try:
                event = self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._event_handler.dispatch(event)
            self._event_queue.task_done()

    async def _drain_events_until_idle(self) -> None:
        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                self._event_handler.dispatch(event)
                self._event_queue.task_done()
                self._process_commands(event)
            except asyncio.TimeoutError:
                if self._state_manager.get_executing_count() == 0:
                    break
        await self._drain_event_queue()
