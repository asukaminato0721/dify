"""Local human-input form models for the FastAPI runtime.

These mappings cover the public standalone form endpoints and the active
workflow pause-time resume-link helpers. Keeping them local avoids importing
the legacy Flask ORM graph on FastAPI-owned human-input paths while form
delivery is ported.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from api_server.db import EnumText, LongText, StringUUID, TypeBase
from graphon.nodes.human_input.enums import HumanInputFormKind, HumanInputFormStatus


class HumanInputForm(TypeBase):
    """Subset of `human_input_forms` needed by the public web form endpoints."""

    __tablename__ = "human_input_forms"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="human_input_forms_pkey"),
        sa.Index("human_input_forms_workflow_run_id_node_id_idx", "workflow_run_id", "node_id"),
        sa.Index("human_input_forms_status_expiration_time_idx", "status", "expiration_time"),
        sa.Index("human_input_forms_status_created_at_idx", "status", "created_at"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    tenant_id: Mapped[str] = mapped_column(StringUUID, init=False)
    app_id: Mapped[str] = mapped_column(StringUUID, init=False)
    workflow_run_id: Mapped[str | None] = mapped_column(StringUUID, init=False)
    form_kind: Mapped[HumanInputFormKind] = mapped_column(EnumText(HumanInputFormKind), init=False)
    node_id: Mapped[str] = mapped_column(sa.String(60), init=False)
    form_definition: Mapped[str] = mapped_column(LongText, init=False)
    rendered_content: Mapped[str] = mapped_column(LongText, init=False)
    status: Mapped[HumanInputFormStatus] = mapped_column(EnumText(HumanInputFormStatus), init=False)
    expiration_time: Mapped[datetime] = mapped_column(DateTime, init=False)
    selected_action_id: Mapped[str | None] = mapped_column(sa.String(200), init=False)
    submitted_data: Mapped[str | None] = mapped_column(LongText, init=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    submission_user_id: Mapped[str | None] = mapped_column(StringUUID, init=False)
    submission_end_user_id: Mapped[str | None] = mapped_column(StringUUID, init=False)
    completed_by_recipient_id: Mapped[str | None] = mapped_column(StringUUID, init=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, init=False)


class HumanInputFormRecipient(TypeBase):
    """Recipient token rows used to resolve public and workflow-pause form links."""

    __tablename__ = "human_input_form_recipients"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="human_input_form_recipients_pkey"),
        sa.Index("human_input_form_recipients_form_id_idx", "form_id"),
        sa.Index("human_input_form_recipients_delivery_id_idx", "delivery_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    form_id: Mapped[str] = mapped_column(StringUUID, init=False)
    delivery_id: Mapped[str] = mapped_column(StringUUID, init=False)
    recipient_type: Mapped[str] = mapped_column(sa.String(255), init=False)
    recipient_payload: Mapped[str] = mapped_column(LongText, init=False)
    access_token: Mapped[str | None] = mapped_column(sa.String(32), init=False)
