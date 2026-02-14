
import time
import pytest
from core.workflow.entities import GraphInitParams
from core.workflow.nodes.start.entities import StartNodeData
from core.workflow.nodes.start.start_node import StartNode
from core.workflow.nodes.trigger_plugin.trigger_event_node import TriggerEventNode
from core.workflow.nodes.trigger_plugin.entities import TriggerEventNodeData
from core.workflow.nodes.trigger_schedule.trigger_schedule_node import TriggerScheduleNode
from core.workflow.nodes.trigger_schedule.entities import TriggerScheduleNodeData
from core.workflow.nodes.trigger_webhook.node import TriggerWebhookNode
from core.workflow.nodes.trigger_webhook.entities import WebhookData
from core.workflow.runtime import GraphRuntimeState, VariablePool
from core.workflow.system_variable import SystemVariable
from core.workflow.constants import SYSTEM_VARIABLE_NODE_ID

def make_node(node_cls, config, user_inputs, system_variables):
    variable_pool = VariablePool(
        system_variables=system_variables,
        user_inputs=user_inputs,
        conversation_variables=[],
    )

    graph_runtime_state = GraphRuntimeState(
        variable_pool=variable_pool,
        start_at=time.perf_counter(),
    )

    return node_cls(
        id="trigger",
        config=config,
        graph_init_params=GraphInitParams(
            tenant_id="tenant",
            app_id="app",
            workflow_id="wf",
            graph_config={},
            user_id="u",
            user_from="account",
            invoke_from="debugger",
            call_depth=0,
        ),
        graph_runtime_state=graph_runtime_state,
    )

def test_start_node_no_system_variables_in_outputs():
    system_variables = SystemVariable(user_id="user_123")
    user_inputs = {"input_1": "value_1"}
    variables = []

    config = {
        "id": "start",
        "data": StartNodeData(title="Start", variables=variables).model_dump(),
    }

    node = make_node(StartNode, config, user_inputs, system_variables)
    result = node._run()

    sys_var_key = f"{SYSTEM_VARIABLE_NODE_ID}.user_id"
    assert result.outputs["input_1"] == "value_1"
    assert sys_var_key not in result.outputs

def test_trigger_event_node_no_system_variables_in_outputs():
    system_variables = SystemVariable(user_id="user_123")
    user_inputs = {"input_1": "value_1"}

    config = {
        "id": "trigger",
        "data": TriggerEventNodeData(
            title="Trigger",
            plugin_id="plugin_id",
            provider_id="provider_id",
            event_name="event_name",
            subscription_id="sub_id",
            plugin_unique_identifier="uniq_id",
            event_parameters={}
        ).model_dump(),
    }

    node = make_node(TriggerEventNode, config, user_inputs, system_variables)
    result = node._run()

    sys_var_key = f"{SYSTEM_VARIABLE_NODE_ID}.user_id"
    assert result.outputs["input_1"] == "value_1"
    assert sys_var_key not in result.outputs

def test_trigger_schedule_node_no_system_variables_in_outputs():
    system_variables = SystemVariable(user_id="user_123")
    user_inputs = {"input_1": "value_1"}

    config = {
        "id": "trigger",
        "data": TriggerScheduleNodeData(
            title="Trigger",
            mode="visual",
            frequency="daily",
            visual_config={"time": "12:00 AM", "on_minute": 0, "weekdays": ["sun"], "monthly_days": [1]},
            timezone="UTC",
        ).model_dump(),
    }

    node = make_node(TriggerScheduleNode, config, user_inputs, system_variables)
    result = node._run()

    sys_var_key = f"{SYSTEM_VARIABLE_NODE_ID}.user_id"
    assert result.outputs["input_1"] == "value_1"
    assert sys_var_key not in result.outputs

def test_trigger_webhook_node_no_system_variables_in_outputs():
    system_variables = SystemVariable(user_id="user_123")
    # For webhook node, user_inputs usually come from external source, here simulated
    user_inputs = {
        "webhook_data": {
            "query_params": {"param1": "value1"},
            "body": {"raw": "body_content"},
            "headers": {"content-type": "text/plain"},
            "files": {}
        }
    }

    config = {
        "id": "trigger",
        "data": WebhookData(
            title="Trigger",
            method="get",
            content_type="text/plain",
            headers=[],
            params=[{"name": "param1"}],
            body=[],
        ).model_dump(),
    }

    node = make_node(TriggerWebhookNode, config, user_inputs, system_variables)
    result = node._run()

    sys_var_key = f"{SYSTEM_VARIABLE_NODE_ID}.user_id"
    assert result.outputs["param1"] == "value1"
    assert sys_var_key not in result.outputs
