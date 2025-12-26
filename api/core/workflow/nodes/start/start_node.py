import json
from typing import Any

from jsonschema import Draft7Validator, ValidationError

from core.app.app_config.entities import VariableEntityType
from core.workflow.constants import SYSTEM_VARIABLE_NODE_ID
from core.workflow.enums import NodeExecutionType, NodeType, WorkflowNodeExecutionStatus
from core.workflow.node_events import NodeRunResult
from core.workflow.nodes.base.node import Node
from core.workflow.nodes.start.entities import StartNodeData


class StartNode(Node[StartNodeData]):
    node_type = NodeType.START
    execution_type = NodeExecutionType.ROOT

    @classmethod
    def version(cls) -> str:
        return "1"

    def _run(self) -> NodeRunResult:
        node_inputs = dict(self.graph_runtime_state.variable_pool.user_inputs)
        self._validate_and_normalize_json_object_inputs(node_inputs)

        outputs = dict(node_inputs)

        return NodeRunResult(status=WorkflowNodeExecutionStatus.SUCCEEDED, inputs=node_inputs, outputs=outputs)

    def _validate_and_normalize_json_object_inputs(self, node_inputs: dict[str, Any]) -> None:
        for variable in self.node_data.variables:
            if variable.type != VariableEntityType.JSON_OBJECT:
                continue

            key = variable.variable
            value = node_inputs.get(key)

            if value is None and variable.required:
                raise ValueError(f"{key} is required in input form")

            schema = variable.json_schema
            if not schema:
                continue

            if not value:
                continue

            try:
                json_schema = json.loads(schema)
            except json.JSONDecodeError as e:
                raise ValueError(f"{schema} must be a valid JSON object")

            try:
                json_value = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError(f"{value} must be a valid JSON object")

            try:
                Draft7Validator(json_schema).validate(json_value)
            except ValidationError as e:
                raise ValueError(f"JSON object for '{key}' does not match schema: {e.message}")
            node_inputs[key] = json_value
