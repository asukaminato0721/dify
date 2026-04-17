"""Asyncio-based worker pool for graph execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import final

from graphon.graph.graph import Graph
from graphon.graph_events.base import GraphNodeEventBase
from graphon.graph_events.node import NodeRunFailedEvent, NodeRunStartedEvent, is_node_result_event
from graphon.node_events.base import NodeRunResult
from graphon.nodes.base.node import Node
from graphon.enums import WorkflowNodeExecutionStatus

from ..layers.base import GraphEngineLayer
from ..ready_queue.async_in_memory import AsyncInMemoryReadyQueue


class AsyncWorker:
    def __init__(
        self,
        *,
        ready_queue: AsyncInMemoryReadyQueue,
        event_queue: asyncio.Queue[GraphNodeEventBase],
        graph: Graph,
        layers: Sequence[GraphEngineLayer],
        worker_id: int,
        execution_context: AbstractContextManager[object] | None = None,
    ) -> None:
        self._ready_queue = ready_queue
        self._event_queue = event_queue
        self._graph = graph
        self._layers = layers
        self._worker_id = worker_id
        self._execution_context = execution_context
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_task_time = time.time()
        self._current_node_started_at: datetime | None = None

    @property
    def is_idle(self) -> bool:
        return (time.time() - self._last_task_time) > 0.2

    @property
    def idle_duration(self) -> float:
        return time.time() - self._last_task_time

    @property
    def worker_id(self) -> int:
        return self._worker_id

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"AsyncGraphWorker-{self._worker_id}")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                node_id = await self._ready_queue.async_get(timeout=0.1)
            except TimeoutError:
                continue
            except asyncio.TimeoutError:
                continue

            self._last_task_time = time.time()
            node = self._graph.nodes[node_id]
            try:
                self._current_node_started_at = None
                await self._execute_node(node)
                self._ready_queue.task_done()
            except Exception as exc:
                await self._event_queue.put(
                    self._build_fallback_failure_event(node, exc, started_at=self._current_node_started_at)
                )
            finally:
                self._current_node_started_at = None

    async def _execute_node(self, node: Node) -> None:
        node.ensure_execution_id()
        error: Exception | None = None
        result_event: GraphNodeEventBase | None = None

        if self._execution_context is not None:
            with self._execution_context:
                self._invoke_node_run_start_hooks(node)
                try:
                    async for event in node.run_async():
                        if isinstance(event, NodeRunStartedEvent) and event.id == node.execution_id:
                            self._current_node_started_at = event.start_at
                        await self._event_queue.put(event)
                        if is_node_result_event(event):
                            result_event = event
                except Exception as exc:
                    error = exc
                    raise
                finally:
                    self._invoke_node_run_end_hooks(node, error, result_event)
        else:
            self._invoke_node_run_start_hooks(node)
            try:
                async for event in node.run_async():
                    if isinstance(event, NodeRunStartedEvent) and event.id == node.execution_id:
                        self._current_node_started_at = event.start_at
                    await self._event_queue.put(event)
                    if is_node_result_event(event):
                        result_event = event
            except Exception as exc:
                error = exc
                raise
            finally:
                self._invoke_node_run_end_hooks(node, error, result_event)

    def _invoke_node_run_start_hooks(self, node: Node) -> None:
        for layer in self._layers:
            try:
                layer.on_node_run_start(node)
            except Exception:
                continue

    def _invoke_node_run_end_hooks(
        self,
        node: Node,
        error: Exception | None,
        result_event: GraphNodeEventBase | None = None,
    ) -> None:
        for layer in self._layers:
            try:
                layer.on_node_run_end(node, error, result_event)
            except Exception:
                continue

    def _build_fallback_failure_event(
        self, node: Node, error: Exception, *, started_at: datetime | None = None
    ) -> NodeRunFailedEvent:
        failure_time = datetime.now(UTC).replace(tzinfo=None)
        error_message = str(error)
        return NodeRunFailedEvent(
            id=node.execution_id,
            node_id=node.id,
            node_type=node.node_type,
            in_iteration_id=None,
            error=error_message,
            start_at=started_at or failure_time,
            finished_at=failure_time,
            node_run_result=NodeRunResult(
                status=WorkflowNodeExecutionStatus.FAILED,
                error=error_message,
                error_type=type(error).__name__,
            ),
        )


@final
class AsyncWorkerPool:
    def __init__(
        self,
        *,
        ready_queue: AsyncInMemoryReadyQueue,
        event_queue: asyncio.Queue[GraphNodeEventBase],
        graph: Graph,
        layers: list[GraphEngineLayer],
        execution_context: AbstractContextManager[object] | None = None,
        initial_count: int = 1,
    ) -> None:
        self._ready_queue = ready_queue
        self._event_queue = event_queue
        self._graph = graph
        self._layers = layers
        self._execution_context = execution_context
        self._initial_count = initial_count
        self._workers: list[AsyncWorker] = []
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for worker_id in range(self._initial_count):
            worker = AsyncWorker(
                ready_queue=self._ready_queue,
                event_queue=self._event_queue,
                graph=self._graph,
                layers=self._layers,
                worker_id=worker_id,
                execution_context=self._execution_context,
            )
            worker.start()
            self._workers.append(worker)

    async def stop_async(self) -> None:
        self._running = False
        for worker in self._workers:
            await worker.stop()
        self._workers.clear()

    def stop(self) -> None:
        self._running = False

    def check_and_scale(self) -> None:
        return
