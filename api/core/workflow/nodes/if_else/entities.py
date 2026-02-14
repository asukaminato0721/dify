from typing import Literal

from pydantic import BaseModel

from core.workflow.nodes.base import BaseNodeData
from core.workflow.utils.condition.entities import Condition


class IfElseNodeData(BaseNodeData):
    """
    If Else Node Data.
    """

    class Case(BaseModel):
        """
        Case entity representing a single logical condition group
        """

        case_id: str
        logical_operator: Literal["and", "or"]
        conditions: list[Condition]

    cases: list[Case] | None = None
