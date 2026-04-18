"""FastAPI-native annotation helpers for `/v1` service API routes."""

from __future__ import annotations

import uuid
from typing import Any, TypedDict, cast

from sqlalchemy import delete, or_, select

from api_server.errors import not_found
from api_server.models.app import App, AppAnnotationHitHistory, AppAnnotationSetting, MessageAnnotation
from extensions.ext_database import db
from extensions.ext_redis import redis_client
from tasks.annotation.add_annotation_to_index_task import add_annotation_to_index_task
from tasks.annotation.delete_annotation_index_task import delete_annotation_index_task
from tasks.annotation.disable_annotation_reply_task import disable_annotation_reply_task
from tasks.annotation.enable_annotation_reply_task import enable_annotation_reply_task
from tasks.annotation.update_annotation_to_index_task import update_annotation_to_index_task


class ServiceApiAnnotationDict(TypedDict):
    id: str
    question: str | None
    answer: str | None
    hit_count: int | None
    created_at: int | None


class ServiceApiAnnotationListDict(TypedDict):
    data: list[ServiceApiAnnotationDict]
    has_more: bool
    limit: int
    total: int
    page: int


class ServiceApiAnnotationReplyStatusDict(TypedDict):
    job_id: str
    job_status: str
    error_msg: str


class ServiceApiAnnotationReplyActionResultDict(TypedDict):
    job_id: str
    job_status: str


class ServiceApiAnnotationService:
    """List and mutate app annotations through local async ORM mappings."""

    @staticmethod
    def _serialize(annotation: MessageAnnotation) -> ServiceApiAnnotationDict:
        return {
            "id": annotation.id,
            "question": annotation.question,
            "answer": annotation.content,
            "hit_count": annotation.hit_count,
            "created_at": int(annotation.created_at.timestamp()) if annotation.created_at is not None else None,
        }

    @classmethod
    async def list_annotations(
        cls,
        *,
        app_id: str,
        page: int,
        limit: int,
        keyword: str,
    ) -> ServiceApiAnnotationListDict:
        stmt = select(MessageAnnotation).where(MessageAnnotation.app_id == app_id)
        if keyword:
            escaped_keyword = keyword[:255]
            stmt = stmt.where(
                or_(
                    MessageAnnotation.question.ilike(f"%{escaped_keyword}%"),
                    MessageAnnotation.content.ilike(f"%{escaped_keyword}%"),
                )
            )
        stmt = stmt.order_by(MessageAnnotation.created_at.desc(), MessageAnnotation.id.desc())

        async with db.session_context() as session:
            total = len((await session.scalars(stmt)).all())
            annotations = (
                await session.scalars(stmt.offset((page - 1) * limit).limit(limit))
            ).all()

        return {
            "data": [cls._serialize(annotation) for annotation in annotations],
            "has_more": len(annotations) == limit,
            "limit": limit,
            "total": total,
            "page": page,
        }

    @classmethod
    async def create_annotation(
        cls,
        *,
        app: App,
        account_id: str,
        tenant_id: str,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotationDict:
        annotation = MessageAnnotation(
            id=str(uuid.uuid4()),
            app_id=app.id,
            question=question,
            content=answer,
            account_id=account_id,
            conversation_id=None,
            message_id=None,
        )

        async with db.session_context() as session:
            async with session.begin():
                session.add(annotation)
            await session.refresh(annotation)

            annotation_setting = await session.scalar(
                select(AppAnnotationSetting).where(AppAnnotationSetting.app_id == app.id).limit(1)
            )

        if annotation_setting is not None:
            cast(Any, add_annotation_to_index_task).delay(
                annotation.id,
                question,
                tenant_id,
                app.id,
                annotation_setting.collection_binding_id,
            )
        return cls._serialize(annotation)

    @classmethod
    async def update_annotation(
        cls,
        *,
        app: App,
        tenant_id: str,
        annotation_id: str,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotationDict:
        async with db.session_context() as session:
            annotation = await session.scalar(
                select(MessageAnnotation).where(
                    MessageAnnotation.id == annotation_id,
                    MessageAnnotation.app_id == app.id,
                )
            )
            if annotation is None:
                raise not_found("annotation_not_found", "Annotation not found.")

            annotation.question = question
            annotation.content = answer
            async with session.begin():
                session.add(annotation)
            await session.refresh(annotation)

            annotation_setting = await session.scalar(
                select(AppAnnotationSetting).where(AppAnnotationSetting.app_id == app.id).limit(1)
            )

        if annotation_setting is not None:
            cast(Any, update_annotation_to_index_task).delay(
                annotation.id,
                annotation.question or annotation.content,
                tenant_id,
                app.id,
                annotation_setting.collection_binding_id,
            )
        return cls._serialize(annotation)

    @classmethod
    async def delete_annotation(
        cls,
        *,
        app: App,
        tenant_id: str,
        annotation_id: str,
    ) -> None:
        async with db.session_context() as session:
            annotation = await session.scalar(
                select(MessageAnnotation).where(
                    MessageAnnotation.id == annotation_id,
                    MessageAnnotation.app_id == app.id,
                )
            )
            if annotation is None:
                raise not_found("annotation_not_found", "Annotation not found.")

            annotation_setting = await session.scalar(
                select(AppAnnotationSetting).where(AppAnnotationSetting.app_id == app.id).limit(1)
            )

            async with session.begin():
                await session.execute(
                    delete(AppAnnotationHitHistory).where(AppAnnotationHitHistory.annotation_id == annotation_id)
                )
                await session.delete(annotation)

        if annotation_setting is not None:
            cast(Any, delete_annotation_index_task).delay(
                annotation.id,
                app.id,
                tenant_id,
                annotation_setting.collection_binding_id,
            )

    @staticmethod
    def trigger_annotation_reply_action(
        *,
        action: str,
        app: App,
        tenant_id: str,
        owner_account_id: str,
        score_threshold: float,
        embedding_provider_name: str,
        embedding_model_name: str,
    ) -> ServiceApiAnnotationReplyActionResultDict:
        match action:
            case "enable":
                cache_key = f"enable_app_annotation_{app.id}"
                job_prefix = "enable_app_annotation_job_"
                cached = redis_client.get(cache_key)
                if cached is not None:
                    cached_job_id = cached.decode() if isinstance(cached, bytes) else str(cached)
                    return {"job_id": cached_job_id, "job_status": "processing"}

                job_id = str(uuid.uuid4())
                redis_client.setnx(f"{job_prefix}{job_id}", "waiting")
                cast(Any, enable_annotation_reply_task).delay(
                    job_id,
                    app.id,
                    owner_account_id,
                    tenant_id,
                    score_threshold,
                    embedding_provider_name,
                    embedding_model_name,
                )
                return {"job_id": job_id, "job_status": "waiting"}
            case "disable":
                cache_key = f"disable_app_annotation_{app.id}"
                job_prefix = "disable_app_annotation_job_"
                cached = redis_client.get(cache_key)
                if cached is not None:
                    cached_job_id = cached.decode() if isinstance(cached, bytes) else str(cached)
                    return {"job_id": cached_job_id, "job_status": "processing"}

                job_id = str(uuid.uuid4())
                redis_client.setnx(f"{job_prefix}{job_id}", "waiting")
                cast(Any, disable_annotation_reply_task).delay(job_id, app.id, tenant_id)
                return {"job_id": job_id, "job_status": "waiting"}
            case _:
                raise not_found("annotation_action_not_found", "The annotation action does not exist.")

    @staticmethod
    def get_annotation_reply_action_status(*, action: str, job_id: str) -> ServiceApiAnnotationReplyStatusDict:
        cache_result = redis_client.get(f"{action}_app_annotation_job_{job_id}")
        if cache_result is None:
            raise not_found("annotation_job_not_found", "The job does not exist.")

        job_status = cache_result.decode() if isinstance(cache_result, bytes) else str(cache_result)
        error_msg = ""
        if job_status == "error":
            error_result = redis_client.get(f"{action}_app_annotation_error_{job_id}")
            if error_result is not None:
                error_msg = error_result.decode() if isinstance(error_result, bytes) else str(error_result)

        return {"job_id": job_id, "job_status": job_status, "error_msg": error_msg}
