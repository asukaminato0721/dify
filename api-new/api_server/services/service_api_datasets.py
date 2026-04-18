"""FastAPI-native dataset list/detail helpers for dataset-token `/v1` routes."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy import func, select

from api_server.errors import forbidden, not_found
from api_server.models.app import Account, Tag, TagBinding, TagType
from api_server.models.dataset import AppDatasetJoin, Dataset, DatasetMetadata, Document
from extensions.ext_database import db
from services.model_provider_service import ModelProviderService


class ServiceApiDatasetTagItemDict(TypedDict):
    id: str
    name: str
    type: str


class ServiceApiDatasetListResponseDict(TypedDict):
    data: list[dict[str, object]]
    has_more: bool
    limit: int
    total: int
    page: int


class ServiceApiDatasetService:
    """Read-only dataset list/detail service for the active dataset-token slice."""

    @staticmethod
    async def _get_dataset(*, tenant_id: str, dataset_id: str) -> Dataset:
        async with db.session_context() as session:
            dataset = await session.scalar(
                select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id)
            )
        if dataset is None:
            raise not_found("dataset_not_found", "Dataset not found.")
        if not dataset.enable_api:
            raise forbidden("dataset_api_disabled", "Dataset api access is not enabled.")
        return dataset

    @staticmethod
    async def _embedding_available(
        *,
        tenant_id: str,
        embedding_model: str | None,
        embedding_provider: str | None,
    ) -> bool:
        if not embedding_model or not embedding_provider:
            return True
        models = ModelProviderService().get_models_by_model_type(tenant_id=tenant_id, model_type="text-embedding")
        model_names = {
            f"{model.models[0].model}:{model.provider}"  # type: ignore[index]
            for model in models
            if getattr(model, "models", None)
        }
        return f"{embedding_model}:{embedding_provider}" in model_names if model_names else True

    @staticmethod
    async def _tags(*, tenant_id: str, dataset_id: str) -> list[ServiceApiDatasetTagItemDict]:
        async with db.session_context() as session:
            tags = (
                await session.scalars(
                    select(Tag)
                    .join(TagBinding, Tag.id == TagBinding.tag_id)
                    .where(
                        TagBinding.target_id == dataset_id,
                        TagBinding.tenant_id == tenant_id,
                        Tag.tenant_id == tenant_id,
                        Tag.type == TagType.KNOWLEDGE,
                    )
                )
            ).all()
        return [{"id": tag.id, "name": tag.name, "type": tag.type.value} for tag in tags]

    @staticmethod
    async def _doc_metadata(*, dataset_id: str, built_in_field_enabled: bool) -> list[dict[str, object]]:
        async with db.session_context() as session:
            metadatas = (
                await session.scalars(select(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset_id))
            ).all()
        items: list[dict[str, object]] = [
            {"id": metadata.id, "name": metadata.name, "type": metadata.type.value} for metadata in metadatas
        ]
        if built_in_field_enabled:
            items.extend(
                [
                    {"id": "built-in", "name": "document_name", "type": "string"},
                    {"id": "built-in", "name": "uploader", "type": "string"},
                    {"id": "built-in", "name": "upload_date", "type": "time"},
                    {"id": "built-in", "name": "last_update_date", "type": "time"},
                    {"id": "built-in", "name": "source", "type": "string"},
                ]
            )
        return items

    @classmethod
    async def _serialize_dataset(cls, dataset: Dataset) -> dict[str, object]:
        async with db.session_context() as session:
            app_count = int(
                (
                    await session.scalar(
                        select(func.count(AppDatasetJoin.id)).where(AppDatasetJoin.dataset_id == dataset.id)
                    )
                )
                or 0
            )
            document_count = int(
                (
                    await session.scalar(select(func.count(Document.id)).where(Document.dataset_id == dataset.id))
                )
                or 0
            )
            total_documents = document_count
            total_available_documents = int(
                (
                    await session.scalar(
                        select(func.count(Document.id)).where(
                            Document.dataset_id == dataset.id,
                            Document.indexing_status == "completed",
                            Document.enabled.is_(True),
                            Document.archived.is_(False),
                        )
                    )
                )
                or 0
            )
            word_count = int(
                (
                    await session.scalar(
                        select(func.coalesce(func.sum(Document.word_count), 0)).where(Document.dataset_id == dataset.id)
                    )
                )
                or 0
            )
            author = await session.scalar(select(Account).where(Account.id == dataset.created_by))

        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "provider": dataset.provider,
            "permission": dataset.permission,
            "data_source_type": dataset.data_source_type,
            "indexing_technique": dataset.indexing_technique,
            "app_count": app_count,
            "document_count": document_count,
            "word_count": word_count,
            "created_by": dataset.created_by,
            "author_name": author.name if author is not None else None,
            "created_at": int(dataset.created_at.timestamp()),
            "updated_by": dataset.updated_by,
            "updated_at": int(dataset.updated_at.timestamp()),
            "embedding_model": dataset.embedding_model,
            "embedding_model_provider": dataset.embedding_model_provider,
            "embedding_available": await cls._embedding_available(
                tenant_id=dataset.tenant_id,
                embedding_model=dataset.embedding_model,
                embedding_provider=dataset.embedding_model_provider,
            ),
            "retrieval_model_dict": dataset.retrieval_model,
            "summary_index_setting": dataset.summary_index_setting,
            "tags": await cls._tags(tenant_id=dataset.tenant_id, dataset_id=dataset.id),
            "doc_form": dataset.chunk_structure or "text_model",
            "external_knowledge_info": None,
            "external_retrieval_model": None,
            "doc_metadata": await cls._doc_metadata(
                dataset_id=dataset.id,
                built_in_field_enabled=dataset.built_in_field_enabled,
            ),
            "built_in_field_enabled": dataset.built_in_field_enabled,
            "pipeline_id": dataset.pipeline_id,
            "runtime_mode": dataset.runtime_mode,
            "chunk_structure": dataset.chunk_structure,
            "icon_info": dataset.icon_info,
            "is_published": False,
            "total_documents": total_documents,
            "total_available_documents": total_available_documents,
            "enable_api": dataset.enable_api,
            "is_multimodal": dataset.is_multimodal,
        }

    @classmethod
    async def list_datasets(
        cls,
        *,
        tenant_id: str,
        page: int,
        limit: int,
        keyword: str | None,
        include_all: bool,
        tag_ids: list[str],
    ) -> ServiceApiDatasetListResponseDict:
        del include_all
        stmt = select(Dataset).where(Dataset.tenant_id == tenant_id).order_by(Dataset.created_at.desc(), Dataset.id)
        if keyword:
            stmt = stmt.where(Dataset.name.ilike(f"%{keyword[:30]}%"))
        if tag_ids:
            stmt = stmt.join(TagBinding, TagBinding.target_id == Dataset.id).where(TagBinding.tag_id.in_(tag_ids))

        async with db.session_context() as session:
            total = len((await session.scalars(stmt)).all())
            datasets = (await session.scalars(stmt.offset((page - 1) * limit).limit(limit))).all()

        return {
            "data": [await cls._serialize_dataset(dataset) for dataset in datasets],
            "has_more": len(datasets) == limit,
            "limit": limit,
            "total": total,
            "page": page,
        }

    @classmethod
    async def get_dataset_detail(cls, *, tenant_id: str, dataset_id: str) -> dict[str, object]:
        dataset = await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        return await cls._serialize_dataset(dataset)
