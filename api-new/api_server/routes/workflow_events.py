"""FastAPI workflow event replay endpoint for public webapp clients."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from api_server.errors import forbidden
from api_server.models.app import AppMode
from api_server.services.webapp_context import WebappContextService
from api_server.services.workflow_events import WorkflowEventsService

router = APIRouter(tags=["workflow-events"])


@router.get("/api/workflow/{task_id}/events")
async def get_workflow_events(
    request: Request,
    task_id: str,
    include_state_snapshot: bool = Query(default=False),
) -> StreamingResponse:
    """Replay workflow events for the authenticated end user's workflow run."""

    context = await WebappContextService.resolve(request)
    if context.app.mode not in {AppMode.WORKFLOW, AppMode.ADVANCED_CHAT}:
        raise forbidden(
            "not_workflow_app",
            "Please check if your Workflow app mode matches the right API route.",
        )

    workflow_run = await WorkflowEventsService.get_accessible_workflow_run(
        workflow_run_id=task_id,
        tenant_id=context.tenant.id,
        app_id=context.app.id,
        end_user_id=context.end_user.id,
    )
    event_stream = WorkflowEventsService.stream_events(
        app_mode=context.app.mode,
        workflow_run=workflow_run,
        end_user=context.end_user,
        include_state_snapshot=include_state_snapshot,
    )
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
