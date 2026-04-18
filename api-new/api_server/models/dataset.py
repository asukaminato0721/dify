"""Minimal dataset models for the active FastAPI service API runtime."""

from __future__ import annotations

import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api_server.db import EnumText, StringUUID, TypeBase


class DatasetMetadataType(enum.StrEnum):
    STRING = "string"
    NUMBER = "number"
    TIME = "time"


class Dataset(TypeBase):
    __tablename__ = "datasets"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="dataset_pkey"),
        sa.Index("dataset_tenant_idx", "tenant_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    tenant_id: Mapped[str] = mapped_column(StringUUID, init=False)
    name: Mapped[str] = mapped_column(String(255), init=False)
    description: Mapped[str | None] = mapped_column(sa.Text, init=False)
    provider: Mapped[str] = mapped_column(String(255), init=False)
    permission: Mapped[str] = mapped_column(String(255), init=False)
    data_source_type: Mapped[str | None] = mapped_column(String(255), init=False)
    indexing_technique: Mapped[str | None] = mapped_column(String(255), init=False)
    created_by: Mapped[str] = mapped_column(StringUUID, init=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, init=False, server_default=func.current_timestamp())
    updated_by: Mapped[str | None] = mapped_column(StringUUID, init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, init=False, server_default=func.current_timestamp())
    embedding_model: Mapped[str | None] = mapped_column(String(255), init=False)
    embedding_model_provider: Mapped[str | None] = mapped_column(String(255), init=False)
    retrieval_model: Mapped[dict[str, object] | None] = mapped_column(sa.JSON, init=False)
    summary_index_setting: Mapped[dict[str, object] | None] = mapped_column(sa.JSON, init=False)
    built_in_field_enabled: Mapped[bool] = mapped_column(sa.Boolean, init=False)
    icon_info: Mapped[dict[str, object] | None] = mapped_column(sa.JSON, init=False)
    runtime_mode: Mapped[str | None] = mapped_column(String(255), init=False)
    pipeline_id: Mapped[str | None] = mapped_column(StringUUID, init=False)
    chunk_structure: Mapped[str | None] = mapped_column(String(255), init=False)
    enable_api: Mapped[bool] = mapped_column(sa.Boolean, init=False)
    is_multimodal: Mapped[bool] = mapped_column(sa.Boolean, init=False)


class DatasetMetadata(TypeBase):
    __tablename__ = "dataset_metadatas"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="dataset_metadata_pkey"),
        sa.Index("dataset_metadata_tenant_idx", "tenant_id"),
        sa.Index("dataset_metadata_dataset_idx", "dataset_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    tenant_id: Mapped[str] = mapped_column(StringUUID, init=False)
    dataset_id: Mapped[str] = mapped_column(StringUUID, init=False)
    type: Mapped[DatasetMetadataType] = mapped_column(EnumText(DatasetMetadataType, length=255), init=False)
    name: Mapped[str] = mapped_column(String(255), init=False)
    created_by: Mapped[str] = mapped_column(StringUUID, init=False)
    updated_by: Mapped[str | None] = mapped_column(StringUUID, init=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        init=False,
        server_default=func.current_timestamp(),
    )


class DatasetMetadataBinding(TypeBase):
    __tablename__ = "dataset_metadata_bindings"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="dataset_metadata_binding_pkey"),
        sa.Index("dataset_metadata_binding_tenant_idx", "tenant_id"),
        sa.Index("dataset_metadata_binding_dataset_idx", "dataset_id"),
        sa.Index("dataset_metadata_binding_metadata_idx", "metadata_id"),
        sa.Index("dataset_metadata_binding_document_idx", "document_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    tenant_id: Mapped[str] = mapped_column(StringUUID, init=False)
    dataset_id: Mapped[str] = mapped_column(StringUUID, init=False)
    metadata_id: Mapped[str] = mapped_column(StringUUID, init=False)
    document_id: Mapped[str] = mapped_column(StringUUID, init=False)


class Document(TypeBase):
    __tablename__ = "documents"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="document_pkey"),
        sa.Index("document_dataset_id_idx", "dataset_id"),
        sa.Index("document_tenant_idx", "tenant_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    tenant_id: Mapped[str] = mapped_column(StringUUID, init=False)
    dataset_id: Mapped[str] = mapped_column(StringUUID, init=False)
    position: Mapped[int] = mapped_column(sa.Integer, init=False)
    data_source_type: Mapped[str] = mapped_column(String(255), init=False)
    data_source_info: Mapped[str | None] = mapped_column(sa.Text, init=False)
    dataset_process_rule_id: Mapped[str | None] = mapped_column(StringUUID, init=False)
    batch: Mapped[str] = mapped_column(String(255), init=False)
    name: Mapped[str] = mapped_column(String(255), init=False)
    created_from: Mapped[str] = mapped_column(String(255), init=False)
    created_by: Mapped[str] = mapped_column(StringUUID, init=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, init=False, server_default=func.current_timestamp())
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    parsing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    cleaning_completed_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    splitting_completed_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    tokens: Mapped[int | None] = mapped_column(sa.Integer, init=False)
    indexing_latency: Mapped[float | None] = mapped_column(sa.Float, init=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    is_paused: Mapped[bool | None] = mapped_column(sa.Boolean, init=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, init=False, server_default=func.current_timestamp())
    word_count: Mapped[int | None] = mapped_column(sa.Integer, init=False)
    indexing_status: Mapped[str] = mapped_column(String(255), init=False)
    error: Mapped[str | None] = mapped_column(sa.Text, init=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, init=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    disabled_by: Mapped[str | None] = mapped_column(StringUUID, init=False)
    archived: Mapped[bool] = mapped_column(sa.Boolean, init=False)
    doc_type: Mapped[str | None] = mapped_column(String(255), init=False)
    doc_form: Mapped[str] = mapped_column(String(255), init=False)
    doc_language: Mapped[str | None] = mapped_column(String(255), init=False)
    need_summary: Mapped[bool] = mapped_column(sa.Boolean, init=False)
    doc_metadata: Mapped[dict[str, object] | None] = mapped_column(sa.JSON, init=False)


class AppDatasetJoin(TypeBase):
    __tablename__ = "app_dataset_joins"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="app_dataset_join_pkey"),
        sa.Index("app_dataset_join_dataset_id_idx", "dataset_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    app_id: Mapped[str] = mapped_column(StringUUID, init=False)
    dataset_id: Mapped[str] = mapped_column(StringUUID, init=False)


class DocumentSegment(TypeBase):
    __tablename__ = "document_segments"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="document_segment_pkey"),
        sa.Index("document_segment_document_id_idx", "document_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID, init=False)
    document_id: Mapped[str] = mapped_column(StringUUID, init=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, init=False)
    status: Mapped[str] = mapped_column(String(255), init=False)
