"""FastAPI wrappers for dataset-token segment endpoints."""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from api_server.errors import bad_request, not_found
from api_server.services.service_api_legacy import dataset_service_current_user, load_legacy_owner_account
from services.dataset_service import DatasetService, DocumentService, SegmentService
from services.summary_index_service import SummaryIndexService
from core.errors.error import LLMBadRequestError, ProviderTokenNotInitError
from core.model_manager import ModelManager
from graphon.model_runtime.entities.model_entities import ModelType
from services.entities.knowledge_entities.knowledge_entities import SegmentUpdateArgs

class ServiceApiSegmentDict(TypedDict):
    id: str
    position: int
    document_id: str
    content: str
    sign_content: str
    answer: str | None
    word_count: int
    tokens: int
    keywords: list[str] | None
    index_node_id: str | None
    index_node_hash: str | None
    hit_count: int
    enabled: bool
    disabled_at: int | None
    disabled_by: str | None
    status: str
    created_by: str
    created_at: int
    updated_at: int
    updated_by: str | None
    indexing_at: int | None
    completed_at: int | None
    error: str | None
    stopped_at: int | None
    child_chunks: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    summary: str | None


class ServiceApiSegmentsResponseDict(TypedDict):
    data: list[ServiceApiSegmentDict]
    doc_form: str
    total: int
    has_more: bool
    limit: int
    page: int


class ServiceApiSegmentDetailResponseDict(TypedDict):
    data: ServiceApiSegmentDict
    doc_form: str


def _timestamp(value) -> int | None:
    return int(value.timestamp()) if value is not None else None


def _serialize_child_chunk(chunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "segment_id": chunk.segment_id,
        "content": chunk.content,
        "position": chunk.position,
        "word_count": chunk.word_count,
        "type": chunk.type,
        "created_at": _timestamp(chunk.created_at),
        "updated_at": _timestamp(chunk.updated_at),
    }


def _serialize_segment(segment, dataset_id: str) -> ServiceApiSegmentDict:
    summary = SummaryIndexService.get_segment_summary(segment_id=segment.id, dataset_id=dataset_id)
    return {
        "id": segment.id,
        "position": segment.position,
        "document_id": segment.document_id,
        "content": segment.content,
        "sign_content": segment.sign_content,
        "answer": segment.answer,
        "word_count": segment.word_count,
        "tokens": segment.tokens,
        "keywords": segment.keywords,
        "index_node_id": segment.index_node_id,
        "index_node_hash": segment.index_node_hash,
        "hit_count": segment.hit_count,
        "enabled": segment.enabled,
        "disabled_at": _timestamp(segment.disabled_at),
        "disabled_by": segment.disabled_by,
        "status": str(segment.status),
        "created_by": segment.created_by,
        "created_at": _timestamp(segment.created_at) or 0,
        "updated_at": _timestamp(segment.updated_at) or 0,
        "updated_by": segment.updated_by,
        "indexing_at": _timestamp(segment.indexing_at),
        "completed_at": _timestamp(segment.completed_at),
        "error": segment.error,
        "stopped_at": _timestamp(segment.stopped_at),
        "child_chunks": [_serialize_child_chunk(chunk) for chunk in segment.child_chunks],
        "attachments": [dict(item) for item in segment.attachments],
        "summary": summary.summary_content if summary else None,
    }


class ServiceApiSegmentService:
    @staticmethod
    def _check_embedding(dataset, tenant_id: str) -> None:
        if dataset.indexing_technique != "high_quality":
            return
        try:
            model_manager = ModelManager.for_tenant(tenant_id=tenant_id)
            model_manager.get_model_instance(
                tenant_id=tenant_id,
                provider=dataset.embedding_model_provider,
                model_type=ModelType.TEXT_EMBEDDING,
                model=dataset.embedding_model,
            )
        except LLMBadRequestError as exc:
            raise bad_request(
                "provider_not_initialize",
                "No Embedding Model available. Please configure a valid provider in the Settings -> Model Provider.",
            ) from exc
        except ProviderTokenNotInitError as exc:
            raise bad_request("provider_not_initialize", exc.description) from exc

    @classmethod
    async def list_segments(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        page: int,
        limit: int,
        status: list[str],
        keyword: str | None,
    ) -> ServiceApiSegmentsResponseDict:
        def _run() -> ServiceApiSegmentsResponseDict:
            owner = load_legacy_owner_account(tenant_id)
            dataset = DatasetService.get_dataset(dataset_id)
            if dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")
            DocumentService.get_document(dataset.id, document_id)
            cls._check_embedding(dataset, tenant_id)
            segments, total = SegmentService.get_segments(
                document_id=document_id,
                tenant_id=tenant_id,
                status_list=status,
                keyword=keyword,
                page=page,
                limit=limit,
            )
            document = DocumentService.get_document(dataset.id, document_id)
            if document is None:
                raise not_found("document_not_found", "Document not found.")
            return {
                "data": [_serialize_segment(segment, dataset_id) for segment in segments],
                "doc_form": document.doc_form,
                "total": total,
                "has_more": len(segments) == limit,
                "limit": limit,
                "page": page,
            }

        return await asyncio.to_thread(_run)

    @classmethod
    async def get_segment(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        segment_id: str,
    ) -> ServiceApiSegmentDetailResponseDict:
        def _run() -> ServiceApiSegmentDetailResponseDict:
            dataset = DatasetService.get_dataset(dataset_id)
            if dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")
            DatasetService.check_dataset_model_setting(dataset)
            document = DocumentService.get_document(dataset_id, document_id)
            if document is None:
                raise not_found("document_not_found", "Document not found.")
            segment = SegmentService.get_segment_by_id(segment_id=segment_id, tenant_id=tenant_id)
            if segment is None:
                raise not_found("segment_not_found", "Segment not found.")
            return {"data": _serialize_segment(segment, dataset_id), "doc_form": document.doc_form}

        return await asyncio.to_thread(_run)

    @classmethod
    async def create_segments(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        segments_payload: list[dict[str, Any]],
    ) -> dict[str, object]:
        def _run() -> dict[str, object]:
            owner = load_legacy_owner_account(tenant_id)
            dataset = DatasetService.get_dataset(dataset_id)
            if dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")
            document = DocumentService.get_document(dataset.id, document_id)
            if document is None:
                raise not_found("document_not_found", "Document not found.")
            if document.indexing_status != "completed":
                raise not_found("document_not_completed", "Document is not completed.")
            if not document.enabled:
                raise not_found("document_disabled", "Document is disabled.")
            cls._check_embedding(dataset, tenant_id)
            with dataset_service_current_user(owner):
                for segment_item in segments_payload:
                    SegmentService.segment_create_args_validate(segment_item, document)
                created_segments = SegmentService.multi_create_segment(segments_payload, document, dataset)
            if not created_segments:
                raise bad_request("segments_not_created", "Segments could not be created.")
            return {
                "data": [_serialize_segment(segment, dataset_id) for segment in created_segments],
                "doc_form": str(document.doc_form),
            }

        return await asyncio.to_thread(_run)

    @classmethod
    async def update_segment(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        segment_id: str,
        payload: SegmentUpdateArgs,
    ) -> ServiceApiSegmentDetailResponseDict:
        def _run() -> ServiceApiSegmentDetailResponseDict:
            owner = load_legacy_owner_account(tenant_id)
            dataset = DatasetService.get_dataset(dataset_id)
            if dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")
            DatasetService.check_dataset_model_setting(dataset)
            document = DocumentService.get_document(dataset_id, document_id)
            if document is None:
                raise not_found("document_not_found", "Document not found.")
            segment = SegmentService.get_segment_by_id(segment_id=segment_id, tenant_id=tenant_id)
            if segment is None:
                raise not_found("segment_not_found", "Segment not found.")
            cls._check_embedding(dataset, tenant_id)
            with dataset_service_current_user(owner):
                updated_segment = SegmentService.update_segment(payload, segment, document, dataset)
            return {"data": _serialize_segment(updated_segment, dataset_id), "doc_form": document.doc_form}

        return await asyncio.to_thread(_run)

    @classmethod
    async def delete_segment(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        segment_id: str,
    ) -> None:
        def _run() -> None:
            owner = load_legacy_owner_account(tenant_id)
            dataset = DatasetService.get_dataset(dataset_id)
            if dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")
            DatasetService.check_dataset_model_setting(dataset)
            document = DocumentService.get_document(dataset_id, document_id)
            if document is None:
                raise not_found("document_not_found", "Document not found.")
            segment = SegmentService.get_segment_by_id(segment_id=segment_id, tenant_id=tenant_id)
            if segment is None:
                raise not_found("segment_not_found", "Segment not found.")
            with dataset_service_current_user(owner):
                SegmentService.delete_segment(segment, document, dataset)

        await asyncio.to_thread(_run)
