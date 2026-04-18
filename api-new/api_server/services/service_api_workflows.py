"""FastAPI-native workflow run lookups for the `/v1` service API slice."""

from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy import select

from api_server.errors import not_found
from api_server.models.workflow import WorkflowRun
from extensions.ext_database import db


class ServiceApiWorkflowRunResponseDict(TypedDict):
    id: str
    workflow_id: str
    status: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    error: str | None
    total_steps: int | None
    total_tokens: int
    created_at: int
    finished_at: int | None
    elapsed_time: float


class ServiceApiWorkflowService:
    """Load workflow-run detail payloads for service API routes."""

    @staticmethod
    async def get_workflow_run(
        *,
        tenant_id: str,
        app_id: str,
        workflow_run_id: str,
    ) -> ServiceApiWorkflowRunResponseDict:
        async with db.session_context() as session:
            workflow_run = await session.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.id == workflow_run_id,
                    WorkflowRun.tenant_id == tenant_id,
                    WorkflowRun.app_id == app_id,
                )
            )

        if workflow_run is None:
            raise not_found("workflow_run_not_found", "Workflow run not found.")

        return {
            "id": workflow_run.id,
            "workflow_id": workflow_run.workflow_id,
            "status": workflow_run.status.value,
            "inputs": workflow_run.inputs_dict,
            "outputs": workflow_run.outputs_dict if workflow_run.status.value != "paused" else {},
            "error": workflow_run.error,
            "total_steps": workflow_run.total_steps,
            "total_tokens": int(workflow_run.total_tokens or 0),
            "created_at": int(workflow_run.created_at.timestamp()),
            "finished_at": int(workflow_run.finished_at.timestamp()) if workflow_run.finished_at is not None else None,
            "elapsed_time": float(workflow_run.elapsed_time or 0.0),
        }
