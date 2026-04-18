"""FastAPI-native dataset metadata helpers for `/v1` service API routes."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import func, select

from api_server.errors import forbidden, not_found
from api_server.models.app import Account
from api_server.models.dataset import Dataset, DatasetMetadata, DatasetMetadataBinding, DatasetMetadataType, Document
from core.rag.index_processor.constant.built_in_field import BuiltInField, MetadataDataSource
from extensions.ext_database import db


class ServiceApiDatasetMetadataItemDict(TypedDict):
    id: str
    name: str
    type: str
    count: int


class ServiceApiDatasetMetadataResponseDict(TypedDict):
    doc_metadata: list[ServiceApiDatasetMetadataItemDict]
    built_in_field_enabled: bool


class ServiceApiDatasetMetadataDetailDict(TypedDict):
    id: str
    type: str
    name: str


class ServiceApiBuiltInFieldItemDict(TypedDict):
    name: str
    type: str


class ServiceApiBuiltInFieldsResponseDict(TypedDict):
    fields: list[ServiceApiBuiltInFieldItemDict]


class ServiceApiMetadataToggleResultDict(TypedDict):
    result: str


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

    @staticmethod
    async def _load_documents(*, dataset_id: str) -> list[Document]:
        async with db.session_context() as session:
            documents = (
                await session.scalars(select(Document).where(Document.dataset_id == dataset_id))
            ).all()
        return list(documents)

    @staticmethod
    async def _account_names_by_id(*, account_ids: set[str]) -> dict[str, str]:
        if not account_ids:
            return {}
        async with db.session_context() as session:
            accounts = (await session.scalars(select(Account).where(Account.id.in_(account_ids)))).all()
        return {account.id: account.name for account in accounts}

    @staticmethod
    def _metadata_detail(metadata: DatasetMetadata) -> ServiceApiDatasetMetadataDetailDict:
        return {"id": metadata.id, "type": metadata.type.value, "name": metadata.name}

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

    @classmethod
    async def create_metadata(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        created_by: str,
        metadata_type: str,
        name: str,
    ) -> ServiceApiDatasetMetadataDetailDict:
        dataset = await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        if len(name) > 255:
            raise forbidden("invalid_metadata_name", "Metadata name cannot exceed 255 characters.")

        async with db.session_context() as session:
            existing = await session.scalar(
                select(DatasetMetadata).where(
                    DatasetMetadata.tenant_id == tenant_id,
                    DatasetMetadata.dataset_id == dataset.id,
                    DatasetMetadata.name == name,
                )
            )
            if existing is not None:
                raise forbidden("metadata_name_exists", "Metadata name already exists.")
            if name in {
                BuiltInField.document_name,
                BuiltInField.uploader,
                BuiltInField.upload_date,
                BuiltInField.last_update_date,
                BuiltInField.source,
            }:
                raise forbidden("metadata_name_exists", "Metadata name already exists in Built-in fields.")

            metadata = DatasetMetadata(
                tenant_id=tenant_id,
                dataset_id=dataset.id,
                type=DatasetMetadataType(metadata_type),
                name=name,
                created_by=created_by,
                updated_by=None,
            )
            async with session.begin():
                session.add(metadata)
            await session.refresh(metadata)
        return cls._metadata_detail(metadata)

    @classmethod
    async def update_metadata_name(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        metadata_id: str,
        updated_by: str,
        name: str,
    ) -> ServiceApiDatasetMetadataDetailDict:
        dataset = await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        if len(name) > 255:
            raise forbidden("invalid_metadata_name", "Metadata name cannot exceed 255 characters.")

        async with db.session_context() as session:
            existing = await session.scalar(
                select(DatasetMetadata).where(
                    DatasetMetadata.tenant_id == tenant_id,
                    DatasetMetadata.dataset_id == dataset.id,
                    DatasetMetadata.name == name,
                )
            )
            if existing is not None and existing.id != metadata_id:
                raise forbidden("metadata_name_exists", "Metadata name already exists.")
            if name in {
                BuiltInField.document_name,
                BuiltInField.uploader,
                BuiltInField.upload_date,
                BuiltInField.last_update_date,
                BuiltInField.source,
            }:
                raise forbidden("metadata_name_exists", "Metadata name already exists in Built-in fields.")

            metadata = await session.scalar(
                select(DatasetMetadata).where(
                    DatasetMetadata.id == metadata_id,
                    DatasetMetadata.dataset_id == dataset.id,
                )
            )
            if metadata is None:
                raise not_found("metadata_not_found", "Metadata not found.")

            old_name = metadata.name
            metadata.name = name
            metadata.updated_by = updated_by

            binding_rows = (
                await session.scalars(
                    select(DatasetMetadataBinding).where(DatasetMetadataBinding.metadata_id == metadata_id)
                )
            ).all()
            if binding_rows:
                document_ids = [binding.document_id for binding in binding_rows]
                documents = (
                    await session.scalars(select(Document).where(Document.id.in_(document_ids)))
                ).all()
                for document in documents:
                    doc_metadata = dict(document.doc_metadata or {})
                    value = doc_metadata.pop(old_name, None)
                    doc_metadata[name] = value
                    document.doc_metadata = doc_metadata
                    session.add(document)

            async with session.begin():
                session.add(metadata)
            await session.refresh(metadata)
        return cls._metadata_detail(metadata)

    @classmethod
    async def delete_metadata(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        metadata_id: str,
    ) -> None:
        dataset = await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)

        async with db.session_context() as session:
            metadata = await session.scalar(
                select(DatasetMetadata).where(
                    DatasetMetadata.id == metadata_id,
                    DatasetMetadata.dataset_id == dataset.id,
                )
            )
            if metadata is None:
                raise not_found("metadata_not_found", "Metadata not found.")

            binding_rows = (
                await session.scalars(
                    select(DatasetMetadataBinding).where(DatasetMetadataBinding.metadata_id == metadata_id)
                )
            ).all()
            if binding_rows:
                document_ids = [binding.document_id for binding in binding_rows]
                documents = (
                    await session.scalars(select(Document).where(Document.id.in_(document_ids)))
                ).all()
                for document in documents:
                    doc_metadata = dict(document.doc_metadata or {})
                    doc_metadata.pop(metadata.name, None)
                    document.doc_metadata = doc_metadata
                    session.add(document)

            async with session.begin():
                for binding in binding_rows:
                    await session.delete(binding)
                await session.delete(metadata)

    @classmethod
    async def toggle_built_in_fields(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        action: str,
    ) -> ServiceApiMetadataToggleResultDict:
        dataset = await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        documents = await cls._load_documents(dataset_id=dataset.id)
        account_names = await cls._account_names_by_id(account_ids={document.created_by for document in documents})

        async with db.session_context() as session:
            session_dataset = await session.scalar(select(Dataset).where(Dataset.id == dataset.id))
            if session_dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")

            for document in documents:
                current = await session.scalar(select(Document).where(Document.id == document.id))
                if current is None:
                    continue

                doc_metadata = dict(current.doc_metadata or {})
                if action == "enable":
                    doc_metadata[BuiltInField.document_name] = current.name
                    doc_metadata[BuiltInField.uploader] = account_names.get(current.created_by)
                    doc_metadata[BuiltInField.upload_date] = current.created_at.timestamp()
                    doc_metadata[BuiltInField.last_update_date] = current.updated_at.timestamp()
                    doc_metadata[BuiltInField.source] = MetadataDataSource[current.data_source_type]
                else:
                    doc_metadata.pop(BuiltInField.document_name, None)
                    doc_metadata.pop(BuiltInField.uploader, None)
                    doc_metadata.pop(BuiltInField.upload_date, None)
                    doc_metadata.pop(BuiltInField.last_update_date, None)
                    doc_metadata.pop(BuiltInField.source, None)

                current.doc_metadata = doc_metadata
                session.add(current)

            session_dataset.built_in_field_enabled = action == "enable"
            async with session.begin():
                session.add(session_dataset)

        return {"result": "success"}
