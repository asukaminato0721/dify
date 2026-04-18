"""Minimal workflow-run models for the active FastAPI runtime.

These mappings intentionally cover only the columns used by the active
FastAPI workflow slice: public workflow generation, workflow event replay,
and `/v1` workflow log/detail routes. Keeping them local avoids importing the
legacy Flask-era ORM graph for read/write paths that are already on the new
runtime while the broader workflow stack is ported incrementally.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api_server.db import EnumText, LongText, StringUUID, TypeBase
from graphon.enums import WorkflowExecutionStatus
from models.enums import CreatorUserRole


class WorkflowAppLogCreatedFrom(StrEnum):
    SERVICE_API = "service-api"
    WEB_APP = "web-app"
    INSTALLED_APP = "installed-app"


class WorkflowRun(TypeBase):
    """Subset of `workflow_runs` used by active FastAPI workflow routes and services."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_run_pkey"),
        sa.Index("workflow_run_triggerd_from_idx", "tenant_id", "app_id", "triggered_from"),
        sa.Index("workflow_run_created_at_id_idx", "created_at", "id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    tenant_id: Mapped[str] = mapped_column(StringUUID, init=False)
    app_id: Mapped[str] = mapped_column(StringUUID, init=False)
    workflow_id: Mapped[str] = mapped_column(StringUUID, init=False)
    triggered_from: Mapped[str] = mapped_column(String(255), init=False)
    version: Mapped[str] = mapped_column(String(255), init=False)
    inputs: Mapped[str | None] = mapped_column(LongText, init=False)
    status: Mapped[WorkflowExecutionStatus] = mapped_column(
        EnumText(WorkflowExecutionStatus, length=255),
        init=False,
    )
    outputs: Mapped[str | None] = mapped_column(LongText, init=False)
    error: Mapped[str | None] = mapped_column(LongText, init=False)
    elapsed_time: Mapped[float] = mapped_column(sa.Float, init=False, server_default=sa.text("0"))
    total_tokens: Mapped[int] = mapped_column(sa.BigInteger, init=False, server_default=sa.text("0"))
    total_steps: Mapped[int | None] = mapped_column(sa.Integer, init=False, server_default=sa.text("0"))
    created_by_role: Mapped[CreatorUserRole] = mapped_column(
        EnumText(CreatorUserRole, length=255),
        init=False,
    )
    created_by: Mapped[str] = mapped_column(StringUUID, init=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        init=False,
        server_default=func.current_timestamp(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    exceptions_count: Mapped[int | None] = mapped_column(sa.Integer, init=False, server_default=sa.text("0"))

    @staticmethod
    def _load_json(raw: str | None, default: dict[str, Any]) -> dict[str, Any]:
        if not raw:
            return default
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return default
        if isinstance(parsed, dict):
            return parsed
        return default

    @property
    def inputs_dict(self) -> dict[str, Any]:
        return self._load_json(self.inputs, {})

    @property
    def outputs_dict(self) -> dict[str, Any]:
        return self._load_json(self.outputs, {})


class WorkflowAppLog(TypeBase):
    """Subset of `workflow_app_logs` needed by active FastAPI workflow paths.

    The copied sync workflow runtime still inserts app-log rows when a public
    run starts. Defining the write-compatible subset here keeps that active
    path off the legacy ORM graph while preserving the existing table shape.
    """

    __tablename__ = "workflow_app_logs"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_app_log_pkey"),
        sa.Index("workflow_app_log_app_idx", "tenant_id", "app_id"),
        sa.Index("workflow_app_log_workflow_run_id_idx", "workflow_run_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        StringUUID,
        init=False,
        insert_default=lambda: str(uuid4()),
        default_factory=lambda: str(uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    workflow_id: Mapped[str] = mapped_column(StringUUID)
    workflow_run_id: Mapped[str] = mapped_column(StringUUID)
    created_from: Mapped[WorkflowAppLogCreatedFrom] = mapped_column(
        EnumText(WorkflowAppLogCreatedFrom, length=255),
    )
    created_by_role: Mapped[CreatorUserRole] = mapped_column(
        EnumText(CreatorUserRole, length=255),
    )
    created_by: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        init=False,
        server_default=func.current_timestamp(),
    )
