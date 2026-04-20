"""
Web App Workflow Resume APIs.
"""

import json
import asyncio
from collections.abc import Generator
from typing import cast

from api_server.models.workflow import WorkflowRun as FastAPIWorkflowRun
from api_server.services.workflow_events import WorkflowEventsService
from controllers.web import api
from controllers.web.error import InvalidArgumentError, NotFoundError
from controllers.web.wraps import WebApiResource
from core.app.apps.advanced_chat.app_generator import AdvancedChatAppGenerator
from core.app.apps.base_app_generator import BaseAppGenerator
from core.app.apps.common.workflow_response_converter import WorkflowResponseConverter
from core.app.apps.message_generator import MessageGenerator
from core.app.apps.workflow.app_generator import WorkflowAppGenerator
from flask import Response, request
from models.enums import CreatorUserRole
from models.model import App, AppMode, EndUser
from services.workflow_event_snapshot_service import build_workflow_event_stream


class WorkflowEventsApi(WebApiResource):
    """API for getting workflow execution events after resume."""

    def get(self, app_model: App, end_user: EndUser, task_id: str):
        """
        Get workflow execution events stream after resume.

        GET /api/workflow/<task_id>/events

        Returns Server-Sent Events stream.
        """
        workflow_run_id = task_id
        workflow_run = asyncio.run(
            WorkflowEventsService.get_accessible_workflow_run(
                workflow_run_id=workflow_run_id,
                tenant_id=app_model.tenant_id,
                app_id=app_model.id,
                end_user_id=end_user.id,
            )
        )

        if workflow_run.finished_at is not None:
            response = WorkflowResponseConverter.workflow_run_result_to_finish_response(
                task_id=workflow_run.id,
                workflow_run=cast(FastAPIWorkflowRun, workflow_run),
                creator_user=end_user,
            )

            payload = response.model_dump(mode="json")
            payload["event"] = response.event.value

            def _generate_finished_events() -> Generator[str, None, None]:
                yield f"data: {json.dumps(payload)}\n\n"

            event_generator = _generate_finished_events
        else:
            app_mode = AppMode.value_of(app_model.mode)
            if app_mode not in {AppMode.ADVANCED_CHAT, AppMode.WORKFLOW}:
                raise InvalidArgumentError(f"cannot subscribe to workflow run, workflow_run_id={workflow_run.id}")
            include_state_snapshot = request.args.get("include_state_snapshot", "false").lower() == "true"
            event_generator = lambda: WorkflowEventsService.stream_events(
                app_mode=app_mode,
                workflow_run=workflow_run,
                end_user=end_user,
                include_state_snapshot=include_state_snapshot,
            )

        return Response(
            event_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )


# Register the APIs
api.add_resource(WorkflowEventsApi, "/workflow/<string:task_id>/events")
