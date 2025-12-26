from typing import Any, Literal, Union

import pytest
from pydantic import ValidationError

from core.workflow.nodes.datasource.entities import DatasourceNodeData


def test_datasource_input_validation():
    # Test "mixed" type
    # mixed expects a string
    data = {
        "value": "some string",
        "type": "mixed"
    }
    input_obj = DatasourceNodeData.DatasourceInput(**data)
    assert input_obj.value == "some string"
    assert input_obj.type == "mixed"

    # mixed with list should fail
    with pytest.raises(ValidationError):
        DatasourceNodeData.DatasourceInput(value=["some", "list"], type="mixed")

    # mixed with int should fail
    with pytest.raises(ValidationError):
        DatasourceNodeData.DatasourceInput(value=123, type="mixed")

    # Test "variable" type
    # variable expects a list of strings
    data = {
        "value": ["some", "var"],
        "type": "variable"
    }
    input_obj = DatasourceNodeData.DatasourceInput(**data)
    assert input_obj.value == ["some", "var"]
    assert input_obj.type == "variable"

    # variable with string should fail
    with pytest.raises(ValidationError):
        DatasourceNodeData.DatasourceInput(value="string", type="variable")

    # variable with list of ints should fail
    with pytest.raises(ValidationError):
        DatasourceNodeData.DatasourceInput(value=[1, 2], type="variable")

    # Test "constant" type
    # constant expects string, int, float, bool

    # string
    input_obj = DatasourceNodeData.DatasourceInput(value="const", type="constant")
    assert input_obj.value == "const"

    # int
    input_obj = DatasourceNodeData.DatasourceInput(value=123, type="constant")
    assert input_obj.value == 123

    # float
    input_obj = DatasourceNodeData.DatasourceInput(value=12.3, type="constant")
    assert input_obj.value == 12.3

    # bool
    input_obj = DatasourceNodeData.DatasourceInput(value=True, type="constant")
    assert input_obj.value == True

    # list should fail
    with pytest.raises(ValidationError):
        DatasourceNodeData.DatasourceInput(value=["list"], type="constant")

    # Test without type (should allow anything compatible with the type hint)
    input_obj = DatasourceNodeData.DatasourceInput(value="anything")
    assert input_obj.value == "anything"
    assert input_obj.type is None

    # Test value=None
    input_obj = DatasourceNodeData.DatasourceInput(value=None)
    assert input_obj.value is None

    # Test dict value (should fail now)
    with pytest.raises(ValidationError):
        DatasourceNodeData.DatasourceInput(value={"some": "dict"})


def test_datasource_node_data_validation():
    # Test valid structure
    data = {
        "title": "My Datasource Node",
        "desc": "Description",
        "plugin_id": "plugin-123",
        "provider_name": "provider-abc",
        "provider_type": "type-xyz",
        "datasource_parameters": {
            "param1": {
                "value": "val1",
                "type": "mixed"
            },
            "param2": {
                "value": ["sys", "var"],
                "type": "variable"
            }
        }
    }

    node_data = DatasourceNodeData(**data)
    assert node_data.datasource_parameters["param1"].value == "val1"
    assert node_data.datasource_parameters["param2"].value == ["sys", "var"]
