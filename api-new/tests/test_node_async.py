from __future__ import annotations

from typing import Any, cast

from graphon.entities.base_node_data import BaseNodeData
from graphon.entities.graph_init_params import GraphInitParams
from graphon.graph_events.node import NodeRunStartedEvent, NodeRunSucceededEvent
from graphon.nodes.base.node import Node
from graphon.runtime.graph_runtime_state import GraphRuntimeState
from graphon.runtime.variable_pool import VariablePool
from graphon.node_events.base import NodeRunResult
from graphon.enums import BuiltinNodeTypes, WorkflowNodeExecutionStatus


class _TestNodeData(BaseNodeData):
    pass


class _AsyncTestNode(Node[_TestNodeData]):
    node_type = BuiltinNodeTypes.CODE

    @classmethod
    def version(cls) -> str:
        return "999"

    async def _run_async(self) -> NodeRunResult:
        return NodeRunResult(status=WorkflowNodeExecutionStatus.SUCCEEDED)

    def _run(self) -> NodeRunResult:
        raise AssertionError("sync path should not be used in this test")


async def test_node_run_async_emits_started_and_succeeded_events() -> None:
    graph_init_params = GraphInitParams(
        workflow_id="workflow-1",
        graph_config={"nodes": [], "edges": []},
        run_context={},
        call_depth=0,
    )
    runtime_state = GraphRuntimeState(variable_pool=VariablePool(), start_at=0.0)
    node = _AsyncTestNode(
        id="node-1",
        config=cast(Any, {"id": "node-1", "data": {"title": "Test", "type": "code"}}),
        graph_init_params=graph_init_params,
        graph_runtime_state=runtime_state,
    )

    events = [event async for event in node.run_async()]

    assert isinstance(events[0], NodeRunStartedEvent)
    assert isinstance(events[1], NodeRunSucceededEvent)
