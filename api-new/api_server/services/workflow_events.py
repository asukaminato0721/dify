"""Workflow event replay helpers for the FastAPI public web runtime.

The initial FastAPI workflow event port supports:
- permission checks against workflow ownership
- finished-run replay from the database
- optional workflow-start snapshot before live pub/sub events

It deliberately avoids the legacy Flask repositories and generators so the
active runtime can stay on FastAPI plus async SQLAlchemy while the broader
workflow stack is still being ported.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from api_server.errors import not_found, service_unavailable
from api_server.models.app import AppMode, CreatorUserRole, EndUser
from api_server.models.workflow import WorkflowRun
from core.app.apps.streaming_utils import stream_topic_events
from core.app.entities.task_entities import WorkflowFinishStreamResponse, WorkflowStartStreamResponse
from extensions.ext_database import db
from extensions.ext_redis import get_pubsub_broadcast_channel
from graphon.entities import WorkflowStartReason
from libs.orjson import orjson_dumps


@dataclass(frozen=True, slots=True)
class WorkflowRunRecord:
    """Stable workflow-run payload used by the FastAPI route layer."""

    id: str
    workflow_id: str
    tenant_id: str
    app_id: str
    inputs: dict[str, Any]
    status: str
    outputs: dict[str, Any]
    error: str | None
    elapsed_time: float
    total_tokens: int
    total_steps: int | None
    created_at: datetime
    finished_at: datetime | None
    exceptions_count: int | None
    created_by_role: CreatorUserRole
    created_by: str


class WorkflowEventsService:
    """Load workflow runs and encode them as FastAPI-native SSE responses."""

    @staticmethod
    async def get_accessible_workflow_run(
        *,
        workflow_run_id: str,
        tenant_id: str,
        app_id: str,
        end_user_id: str,
    ) -> WorkflowRunRecord:
        """Return a workflow run only when it belongs to the current end user."""

        async with db.session_context() as session:
            workflow_run = await session.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.id == workflow_run_id,
                    WorkflowRun.tenant_id == tenant_id,
                    WorkflowRun.app_id == app_id,
                )
            )

        if workflow_run is None:
            raise not_found("not_found", "Workflow run not found.")
        if workflow_run.created_by_role != CreatorUserRole.END_USER or workflow_run.created_by != end_user_id:
            raise not_found("not_found", "Workflow run not found.")

        return WorkflowRunRecord(
            id=workflow_run.id,
            workflow_id=workflow_run.workflow_id,
            tenant_id=workflow_run.tenant_id,
            app_id=workflow_run.app_id,
            inputs=workflow_run.inputs_dict,
            status=workflow_run.status.value,
            outputs=workflow_run.outputs_dict,
            error=workflow_run.error,
            elapsed_time=float(workflow_run.elapsed_time or 0.0),
            total_tokens=int(workflow_run.total_tokens or 0),
            total_steps=int(workflow_run.total_steps or 0) if workflow_run.total_steps is not None else None,
            created_at=workflow_run.created_at,
            finished_at=workflow_run.finished_at,
            exceptions_count=workflow_run.exceptions_count,
            created_by_role=workflow_run.created_by_role,
            created_by=workflow_run.created_by,
        )

    @classmethod
    def stream_events(
        cls,
        *,
        app_mode: AppMode,
        workflow_run: WorkflowRunRecord,
        end_user: EndUser,
        include_state_snapshot: bool,
    ) -> Iterator[str]:
        """Encode workflow replay and live events as SSE chunks."""

        if workflow_run.finished_at is not None:
            return cls._finished_event_stream(workflow_run=workflow_run, end_user=end_user)

        live_events = cls._live_events(app_mode=app_mode, workflow_run_id=workflow_run.id)
        return cls._live_event_stream(
            workflow_run=workflow_run,
            live_events=live_events,
            include_state_snapshot=include_state_snapshot,
        )

    @staticmethod
    def _finished_event_stream(*, workflow_run: WorkflowRunRecord, end_user: EndUser) -> Iterator[str]:
        yield _encode_sse_message(_build_finished_event(workflow_run=workflow_run, end_user=end_user))

    @staticmethod
    def _live_event_stream(
        *,
        workflow_run: WorkflowRunRecord,
        live_events: Generator[Mapping[str, Any] | str, None, None],
        include_state_snapshot: bool,
    ) -> Iterator[str]:
        snapshot_sent = False
        for message in live_events:
            yield _encode_sse_message(message)
            if include_state_snapshot and not snapshot_sent:
                yield _encode_sse_message(_build_started_event(workflow_run=workflow_run))
                snapshot_sent = True

    @staticmethod
    def _live_events(*, app_mode: AppMode, workflow_run_id: str) -> Generator[Mapping[str, Any] | str, None, None]:
        """Subscribe to the workflow run topic after validating Redis availability."""

        try:
            topic = get_pubsub_broadcast_channel().topic(
                _build_channel_key(app_mode=app_mode, workflow_run_id=workflow_run_id)
            )
        except AssertionError as exc:
            raise service_unavailable(
                "workflow_stream_unavailable",
                "Workflow event streaming is unavailable.",
            ) from exc

        return stream_topic_events(
            topic=topic,
            idle_timeout=300,
            ping_interval=10.0,
        )


def _build_channel_key(*, app_mode: AppMode, workflow_run_id: str) -> str:
    return f"channel:{app_mode}:{workflow_run_id}"


def _build_started_event(*, workflow_run: WorkflowRunRecord) -> dict[str, Any]:
    response = WorkflowStartStreamResponse(
        task_id=workflow_run.id,
        workflow_run_id=workflow_run.id,
        data=WorkflowStartStreamResponse.Data(
            id=workflow_run.id,
            workflow_id=workflow_run.workflow_id,
            inputs=workflow_run.inputs,
            created_at=int(workflow_run.created_at.timestamp()),
            reason=WorkflowStartReason.INITIAL,
        ),
    )
    payload = response.model_dump(mode="json")
    payload["event"] = response.event.value
    return payload


def _build_finished_event(*, workflow_run: WorkflowRunRecord, end_user: EndUser) -> dict[str, Any]:
    assert workflow_run.finished_at is not None
    response = WorkflowFinishStreamResponse(
        task_id=workflow_run.id,
        workflow_run_id=workflow_run.id,
        data=WorkflowFinishStreamResponse.Data(
            id=workflow_run.id,
            workflow_id=workflow_run.workflow_id,
            status=workflow_run.status,
            outputs=workflow_run.outputs,
            error=workflow_run.error,
            elapsed_time=workflow_run.elapsed_time,
            total_tokens=workflow_run.total_tokens,
            total_steps=workflow_run.total_steps or 0,
            created_by={
                "id": end_user.id,
                "user": end_user.session_id,
            },
            created_at=int(workflow_run.created_at.timestamp()),
            finished_at=int(workflow_run.finished_at.timestamp()),
            files=[],
            exceptions_count=workflow_run.exceptions_count,
        ),
    )
    payload = response.model_dump(mode="json")
    payload["event"] = response.event.value
    return payload


def _encode_sse_message(message: Mapping[str, Any] | str) -> str:
    if isinstance(message, str):
        return f"event: {message}\n\n"
    return f"data: {orjson_dumps(message)}\n\n"
