"""FastAPI-native read-only document helpers for dataset-token `/v1` routes."""

from __future__ import annotations

import json
from typing import TypedDict

from sqlalchemy import desc, func, select

from api_server.errors import bad_request, not_found
from api_server.models.app import Account, UploadFile
from api_server.models.dataset import Dataset, DatasetMetadata, DatasetMetadataBinding, Document, DocumentSegment
from core.rag.index_processor.constant.built_in_field import BuiltInField, MetadataDataSource
from extensions.ext_database import db


class ServiceApiDocumentListResponseDict(TypedDict):
    data: list[dict[str, object]]
    has_more: bool
    limit: int
    total: int
    page: int


class ServiceApiDocumentStatusItemDict(TypedDict):
    id: str
    indexing_status: str
    processing_started_at: int | None
    parsing_completed_at: int | None
    cleaning_completed_at: int | None
    splitting_completed_at: int | None
    completed_at: int | None
    paused_at: int | None
    error: str | None
    stopped_at: int | None
    completed_segments: int
    total_segments: int


class ServiceApiDocumentStatusResponseDict(TypedDict):
    data: list[ServiceApiDocumentStatusItemDict]


class ServiceApiDocumentService:
    """Read-only dataset document endpoints using local async ORM mappings."""

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.timestamp())

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
            raise bad_request("dataset_api_disabled", "Dataset api access is not enabled.")
        return dataset

    @staticmethod
    def _display_status(document: Document) -> str | None:
        if document.indexing_status == "waiting":
            return "queuing"
        if document.indexing_status not in {"completed", "error", "waiting"} and document.is_paused:
            return "paused"
        if document.indexing_status in {"parsing", "cleaning", "splitting", "indexing"}:
            return "indexing"
        if document.indexing_status == "error":
            return "error"
        if document.indexing_status == "completed" and not document.archived and document.enabled:
            return "available"
        if document.indexing_status == "completed" and not document.archived and not document.enabled:
            return "disabled"
        if document.indexing_status == "completed" and document.archived:
            return "archived"
        return None

    @staticmethod
    async def _account_names(*, account_ids: set[str]) -> dict[str, str]:
        if not account_ids:
            return {}
        async with db.session_context() as session:
            accounts = (await session.scalars(select(Account).where(Account.id.in_(account_ids)))).all()
        return {account.id: account.name for account in accounts}

    @classmethod
    async def _doc_metadata_details(cls, *, dataset_id: str, document: Document) -> list[dict[str, object]] | None:
        if not document.doc_metadata:
            return None
        async with db.session_context() as session:
            metadatas = (
                await session.scalars(
                    select(DatasetMetadata)
                    .join(DatasetMetadataBinding, DatasetMetadataBinding.metadata_id == DatasetMetadata.id)
                    .where(
                        DatasetMetadataBinding.dataset_id == dataset_id,
                        DatasetMetadataBinding.document_id == document.id,
                    )
                )
            ).all()

        metadata_list = [
            {
                "id": metadata.id,
                "name": metadata.name,
                "type": metadata.type.value,
                "value": document.doc_metadata.get(metadata.name),
            }
            for metadata in metadatas
        ]
        metadata_list.extend(await cls._built_in_fields(document=document))
        return metadata_list

    @classmethod
    async def _built_in_fields(cls, *, document: Document) -> list[dict[str, object]]:
        uploader_names = await cls._account_names(account_ids={document.created_by})
        return [
            {"id": "built-in", "name": BuiltInField.document_name, "type": "string", "value": document.name},
            {
                "id": "built-in",
                "name": BuiltInField.uploader,
                "type": "string",
                "value": uploader_names.get(document.created_by),
            },
            {
                "id": "built-in",
                "name": BuiltInField.upload_date,
                "type": "time",
                "value": str(document.created_at.timestamp()),
            },
            {
                "id": "built-in",
                "name": BuiltInField.last_update_date,
                "type": "time",
                "value": str(document.updated_at.timestamp()),
            },
            {
                "id": "built-in",
                "name": BuiltInField.source,
                "type": "string",
                "value": MetadataDataSource[document.data_source_type],
            },
        ]

    @staticmethod
    def _data_source_info(document: Document) -> dict[str, object]:
        if not document.data_source_info:
            return {}
        try:
            return json.loads(document.data_source_info)
        except json.JSONDecodeError:
            return {}

    @classmethod
    async def _data_source_detail(cls, *, document: Document) -> dict[str, object]:
        info = cls._data_source_info(document)
        if document.data_source_type == "upload_file":
            upload_file_id = info.get("upload_file_id")
            if isinstance(upload_file_id, str):
                async with db.session_context() as session:
                    file_detail = await session.scalar(select(UploadFile).where(UploadFile.id == upload_file_id))
                if file_detail is not None:
                    return {
                        "upload_file": {
                            "id": file_detail.id,
                            "name": file_detail.name,
                            "size": file_detail.size,
                            "extension": file_detail.extension,
                            "mime_type": file_detail.mime_type,
                            "created_by": file_detail.created_by,
                            "created_at": file_detail.created_at.timestamp() if file_detail.created_at else None,
                        }
                    }
        return info

    @classmethod
    async def _serialize_document(cls, *, dataset_id: str, document: Document) -> dict[str, object]:
        return {
            "id": document.id,
            "position": document.position,
            "data_source_type": document.data_source_type,
            "data_source_info": cls._data_source_info(document),
            "data_source_detail_dict": await cls._data_source_detail(document=document),
            "dataset_process_rule_id": document.dataset_process_rule_id,
            "name": document.name,
            "created_from": document.created_from,
            "created_by": document.created_by,
            "created_at": cls._timestamp(document.created_at),
            "tokens": document.tokens,
            "indexing_status": document.indexing_status,
            "error": document.error,
            "enabled": document.enabled,
            "disabled_at": cls._timestamp(document.disabled_at),
            "disabled_by": document.disabled_by,
            "archived": document.archived,
            "display_status": cls._display_status(document),
            "word_count": document.word_count,
            "hit_count": 0,
            "doc_form": document.doc_form,
            "doc_metadata": await cls._doc_metadata_details(dataset_id=dataset_id, document=document),
            "summary_index_status": None,
            "need_summary": document.need_summary,
        }

    @classmethod
    async def list_documents(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        page: int,
        limit: int,
        keyword: str | None,
        status: str | None,
    ) -> ServiceApiDocumentListResponseDict:
        await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        stmt = select(Document).where(Document.dataset_id == dataset_id, Document.tenant_id == tenant_id)
        if status:
            status_map = {
                "queuing": ("waiting", False, False, True),
                "paused": (None, True, None, None),
                "indexing": ("indexing", False, None, None),
                "error": ("error", False, None, None),
                "available": ("completed", False, False, None),
                "disabled": ("completed", False, False, False),
                "archived": ("completed", False, True, None),
            }
            status_tuple = status_map.get(status)
            if status_tuple:
                indexing_status, is_paused, archived, enabled = status_tuple
                if indexing_status is not None:
                    stmt = stmt.where(Document.indexing_status == indexing_status)
                if is_paused is not None:
                    stmt = stmt.where(Document.is_paused.is_(is_paused))
                if archived is not None:
                    stmt = stmt.where(Document.archived.is_(archived))
                if enabled is not None:
                    stmt = stmt.where(Document.enabled.is_(enabled))
        if keyword:
            stmt = stmt.where(Document.name.like(f"%{keyword}%"))
        stmt = stmt.order_by(desc(Document.created_at), desc(Document.position))

        async with db.session_context() as session:
            total = len((await session.scalars(stmt)).all())
            documents = (await session.scalars(stmt.offset((page - 1) * limit).limit(limit))).all()

        return {
            "data": [await cls._serialize_document(dataset_id=dataset_id, document=document) for document in documents],
            "has_more": len(documents) == limit,
            "limit": limit,
            "total": total,
            "page": page,
        }

    @classmethod
    async def get_document_detail(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        metadata: str,
    ) -> dict[str, object]:
        await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        async with db.session_context() as session:
            document = await session.scalar(
                select(Document).where(
                    Document.dataset_id == dataset_id,
                    Document.tenant_id == tenant_id,
                    Document.id == document_id,
                )
            )
        if document is None:
            raise not_found("document_not_found", "Document not found.")
        if metadata not in {"all", "only", "without"}:
            raise bad_request("invalid_metadata", f"Invalid metadata value: {metadata}")

        if metadata == "only":
            return {
                "id": document.id,
                "doc_type": document.doc_type,
                "doc_metadata": await cls._doc_metadata_details(dataset_id=dataset_id, document=document),
            }

        response: dict[str, object] = {
            "id": document.id,
            "position": document.position,
            "data_source_type": document.data_source_type,
            "data_source_info": await cls._data_source_detail(document=document),
            "dataset_process_rule_id": document.dataset_process_rule_id,
            "dataset_process_rule": None,
            "document_process_rule": None,
            "name": document.name,
            "created_from": document.created_from,
            "created_by": document.created_by,
            "created_at": cls._timestamp(document.created_at),
            "tokens": document.tokens,
            "indexing_status": document.indexing_status,
            "completed_at": cls._timestamp(document.completed_at),
            "updated_at": cls._timestamp(document.updated_at),
            "indexing_latency": document.indexing_latency,
            "error": document.error,
            "enabled": document.enabled,
            "disabled_at": cls._timestamp(document.disabled_at),
            "disabled_by": document.disabled_by,
            "archived": document.archived,
            "segment_count": 0,
            "average_segment_length": 0,
            "hit_count": 0,
            "display_status": cls._display_status(document),
            "doc_form": document.doc_form,
            "doc_language": document.doc_language,
            "summary_index_status": None,
            "need_summary": document.need_summary,
        }
        if metadata == "all":
            response["doc_type"] = document.doc_type
            response["doc_metadata"] = await cls._doc_metadata_details(dataset_id=dataset_id, document=document)
        return response

    @classmethod
    async def get_batch_indexing_status(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        batch: str,
    ) -> ServiceApiDocumentStatusResponseDict:
        await cls._get_dataset(tenant_id=tenant_id, dataset_id=dataset_id)
        async with db.session_context() as session:
            documents = (
                await session.scalars(
                    select(Document).where(
                        Document.dataset_id == dataset_id,
                        Document.tenant_id == tenant_id,
                        Document.batch == batch,
                    )
                )
            ).all()
            if not documents:
                raise not_found("documents_not_found", "Documents not found.")

            data: list[ServiceApiDocumentStatusItemDict] = []
            for document in documents:
                completed_segments = int(
                    (
                        await session.scalar(
                            select(func.count(DocumentSegment.id)).where(
                                DocumentSegment.document_id == document.id,
                                DocumentSegment.completed_at.is_not(None),
                                DocumentSegment.status != "re_segment",
                            )
                        )
                    )
                    or 0
                )
                total_segments = int(
                    (
                        await session.scalar(
                            select(func.count(DocumentSegment.id)).where(
                                DocumentSegment.document_id == document.id,
                                DocumentSegment.status != "re_segment",
                            )
                        )
                    )
                    or 0
                )
                data.append(
                    {
                        "id": document.id,
                        "indexing_status": "paused" if document.is_paused else document.indexing_status,
                        "processing_started_at": cls._timestamp(document.processing_started_at),
                        "parsing_completed_at": cls._timestamp(document.parsing_completed_at),
                        "cleaning_completed_at": cls._timestamp(document.cleaning_completed_at),
                        "splitting_completed_at": cls._timestamp(document.splitting_completed_at),
                        "completed_at": cls._timestamp(document.completed_at),
                        "paused_at": cls._timestamp(document.paused_at),
                        "error": document.error,
                        "stopped_at": cls._timestamp(document.stopped_at),
                        "completed_segments": completed_segments,
                        "total_segments": total_segments,
                    }
                )
        return {"data": data}
