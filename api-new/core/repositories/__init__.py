"""Repository package exports.

The FastAPI migration only needs a small subset of repository names during
module import. Concrete implementations are therefore loaded lazily so package
imports do not pull optional file-processing and workflow dependencies into
unrelated runtime paths.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .factory import (
    DifyCoreRepositoryFactory,
    OrderConfig,
    RepositoryImportError,
    WorkflowExecutionRepository,
    WorkflowNodeExecutionRepository,
)

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "CeleryWorkflowExecutionRepository": (
        "core.repositories.celery_workflow_execution_repository",
        "CeleryWorkflowExecutionRepository",
    ),
    "CeleryWorkflowNodeExecutionRepository": (
        "core.repositories.celery_workflow_node_execution_repository",
        "CeleryWorkflowNodeExecutionRepository",
    ),
    "SQLAlchemyWorkflowExecutionRepository": (
        "core.repositories.sqlalchemy_workflow_execution_repository",
        "SQLAlchemyWorkflowExecutionRepository",
    ),
    "SQLAlchemyWorkflowNodeExecutionRepository": (
        "core.repositories.sqlalchemy_workflow_node_execution_repository",
        "SQLAlchemyWorkflowNodeExecutionRepository",
    ),
}

__all__ = [
    "CeleryWorkflowExecutionRepository",
    "CeleryWorkflowNodeExecutionRepository",
    "DifyCoreRepositoryFactory",
    "OrderConfig",
    "RepositoryImportError",
    "SQLAlchemyWorkflowExecutionRepository",
    "SQLAlchemyWorkflowNodeExecutionRepository",
    "WorkflowExecutionRepository",
    "WorkflowNodeExecutionRepository",
]


def __getattr__(name: str) -> Any:
    lazy_target = _LAZY_EXPORTS.get(name)
    if lazy_target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = lazy_target
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
