"""FastAPI-native dataset metadata helpers for `/v1` service API routes."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import func, select

from api_server.errors import forbidden, not_found
from api_server.models.dataset import Dataset, DatasetMetadata, DatasetMetadataBinding
from core.rag.index_processor.constant.built_in_field import BuiltInField
from extensions.ext_database import db


class ServiceApiDatasetMetadataItemDict(TypedDict):
    id: str
    name: str
    type: str
    count: int


class ServiceApiDatasetMetadataResponseDict(TypedDict):
    doc_metadata: list[ServiceApiDatasetMetadataItemDict]
    built_in_field_enabled: bool


class ServiceApiBuiltInFieldItemDict(TypedDict):
    name: str
    type: str


class ServiceApiBuiltInFieldsResponseDict(TypedDict):
    fields: list[ServiceApiBuiltInFieldItemDict]


class ServiceApiDatasetMetadataService:
    """Read-only dataset metadata endpoints for the dataset-token service API slice."""

    @staticmethod
    async def _get_dataset(*, tenant_id: str, dataset_id: str) -> Dataset:
        async with db.session_context() as session:
            dataset = await session.scalar(
                select(Dataset).where(
                    Dataset.id == dataset_id,
                    Dataset.tenant_id == tenant_id,
                )
            )
        if dataset is None:
            raise not_found("dataset_not_found", "Dataset not found.")
        if not dataset.enable_api:
            raise forbidden("dataset_api_disabled", "Dataset api access is not enabled.")
        return dataset

    @classmethod
    async def get_dataset_metadata(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
    ) -> ServiceApiDatasetMetadataResponseDict:
        dataset = await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)

        async with db.session_context() as session:
            metadatas = (
                await session.scalars(
                    select(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset.id)
                )
            ).all()

            counts_by_id: dict[str, int] = {}
            for metadata in metadatas:
                counts_by_id[metadata.id] = int(
                    (
                        await session.scalar(
                            select(func.count(DatasetMetadataBinding.id)).where(
                                DatasetMetadataBinding.metadata_id == metadata.id,
                                DatasetMetadataBinding.dataset_id == dataset.id,
                            )
                        )
                    )
                    or 0
                )

        return {
            "doc_metadata": [
                {
                    "id": metadata.id,
                    "name": metadata.name,
                    "type": metadata.type.value,
                    "count": counts_by_id.get(metadata.id, 0),
                }
                for metadata in metadatas
            ],
            "built_in_field_enabled": dataset.built_in_field_enabled,
        }

    @staticmethod
    async def get_built_in_fields(
        *,
        tenant_id: str,
        dataset_id: str,
    ) -> ServiceApiBuiltInFieldsResponseDict:
        await ServiceApiDatasetMetadataService._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        return {
            "fields": [
                {"name": BuiltInField.document_name, "type": "string"},
                {"name": BuiltInField.uploader, "type": "string"},
                {"name": BuiltInField.upload_date, "type": "time"},
                {"name": BuiltInField.last_update_date, "type": "time"},
                {"name": BuiltInField.source, "type": "string"},
            ]
        }
