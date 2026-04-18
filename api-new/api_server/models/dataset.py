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
    built_in_field_enabled: Mapped[bool] = mapped_column(sa.Boolean, init=False)
    enable_api: Mapped[bool] = mapped_column(sa.Boolean, init=False)


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
    data_source_type: Mapped[str] = mapped_column(String(255), init=False)
    name: Mapped[str] = mapped_column(String(255), init=False)
    created_by: Mapped[str] = mapped_column(StringUUID, init=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, init=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, init=False, server_default=func.current_timestamp())
    doc_metadata: Mapped[dict[str, object] | None] = mapped_column(sa.JSON, init=False)
