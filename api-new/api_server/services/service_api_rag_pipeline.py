"""FastAPI wrappers for dataset-token RAG pipeline endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Generator, Mapping
from typing import Any, TypedDict, cast

from api_server.errors import bad_request
from api_server.services.service_api_legacy import load_legacy_owner_account
from core.db.session_factory import get_sync_session_maker
from core.app.apps.pipeline.pipeline_generator import PipelineGenerator
from core.app.entities.app_invoke_entities import InvokeFrom
from services.file_service import FileService
from services.rag_pipeline.entity.pipeline_service_api_entities import DatasourceNodeRunApiEntity, PipelineRunApiEntity
from services.rag_pipeline.pipeline_generate_service import PipelineGenerateService
from services.rag_pipeline.rag_pipeline import RagPipelineService


class ServiceApiPipelineUploadFileDict(TypedDict):
    id: str
    name: str
    size: int
    extension: str
    mime_type: str | None
    created_by: str
    created_at: str | None


class ServiceApiRagPipelineService:
    @staticmethod
    def _serialize_upload_file(upload_file) -> ServiceApiPipelineUploadFileDict:
        return {
            "id": upload_file.id,
            "name": upload_file.name,
            "size": upload_file.size,
            "extension": upload_file.extension,
            "mime_type": upload_file.mime_type,
            "created_by": upload_file.created_by,
            "created_at": upload_file.created_at.isoformat() if upload_file.created_at else None,
        }

    @classmethod
    async def upload_pipeline_file(
        cls,
        *,
        tenant_id: str,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> ServiceApiPipelineUploadFileDict:
        def _run() -> ServiceApiPipelineUploadFileDict:
            owner_account = load_legacy_owner_account(tenant_id)
            upload_file = FileService(cast(Any, get_sync_session_maker())).upload_file(
                filename=filename,
                content=content,
                mimetype=mime_type,
                user=owner_account,
            )
            return cls._serialize_upload_file(upload_file)

        return await asyncio.to_thread(_run)

    @staticmethod
    async def list_datasource_plugins(
        *,
        tenant_id: str,
        dataset_id: str,
        is_published: bool,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            RagPipelineService().get_datasource_plugins,
            tenant_id,
            dataset_id,
            is_published,
        )

    @staticmethod
    async def run_datasource_node(
        *,
        tenant_id: str,
        dataset_id: str,
        node_id: str,
        payload: DatasourceNodeRunApiEntity,
    ) -> Mapping[str, Any] | Generator[str, None, None]:
        def _run() -> Mapping[str, Any] | Generator[str, None, None]:
            owner_account = load_legacy_owner_account(tenant_id)
            rag_pipeline_service = RagPipelineService()
            pipeline = rag_pipeline_service.get_pipeline(tenant_id=tenant_id, dataset_id=dataset_id)
            return PipelineGenerator.convert_to_event_stream(
                rag_pipeline_service.run_datasource_workflow_node(
                    pipeline=pipeline,
                    node_id=node_id,
                    user_inputs=payload.inputs,
                    account=owner_account,
                    datasource_type=payload.datasource_type,
                    is_published=payload.is_published,
                    credential_id=payload.credential_id,
                )
            )

        return await asyncio.to_thread(_run)

    @staticmethod
    async def run_pipeline(
        *,
        tenant_id: str,
        dataset_id: str,
        payload: PipelineRunApiEntity,
    ) -> Mapping[str, Any] | Generator[str, None, None]:
        def _run() -> Mapping[str, Any] | Generator[str, None, None]:
            owner_account = load_legacy_owner_account(tenant_id)
            rag_pipeline_service = RagPipelineService()
            pipeline = rag_pipeline_service.get_pipeline(tenant_id=tenant_id, dataset_id=dataset_id)
            try:
                return PipelineGenerateService.generate(
                    pipeline=pipeline,
                    user=owner_account,
                    args=payload.model_dump(),
                    invoke_from=InvokeFrom.PUBLISHED_PIPELINE if payload.is_published else InvokeFrom.DEBUGGER,
                    streaming=payload.response_mode == "streaming",
                )
            except Exception as exc:
                raise bad_request("pipeline_run_error", str(exc)) from exc

        return await asyncio.to_thread(_run)
