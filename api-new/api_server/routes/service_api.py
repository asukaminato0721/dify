"""FastAPI service API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from fastapi import APIRouter, Form, Query, Request
from fastapi import File as FastAPIFile
from fastapi import UploadFile as FastAPIUploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api_server.errors import forbidden
from api_server.models.app import EndUser, Site
from api_server.routes.files import _build_file_response
from api_server.services.audio import PublicAudioService
from api_server.services.conversation_message import (
    ConversationItemDict,
    ConversationMessageService,
    ConversationPaginationDict,
    MessagePaginationDict,
    ResultDict,
)
from api_server.services.generation import AsyncWebGenerationService
from api_server.services.generation_bridge import PublicGenerationBridge
from api_server.services.service_api_annotations import (
    ServiceApiAnnotationDict,
    ServiceApiAnnotationListDict,
    ServiceApiAnnotationReplyActionResultDict,
    ServiceApiAnnotationReplyStatusDict,
    ServiceApiAnnotationService,
)
from api_server.services.service_api_apps import AppInfoResponseDict, ServiceApiAppService, ToolIconsResponseDict
from api_server.services.service_api_auth import ServiceApiAuthService
from api_server.services.service_api_conversation_variables import (
    ServiceApiConversationVariableDict,
    ServiceApiConversationVariablePaginationDict,
    ServiceApiConversationVariableService,
)
from api_server.services.service_api_dataset_metadata import (
    ServiceApiBuiltInFieldsResponseDict,
    ServiceApiDatasetMetadataResponseDict,
    ServiceApiDatasetMetadataService,
)
from api_server.services.service_api_feedbacks import ServiceApiFeedbackListResponseDict, ServiceApiFeedbackService
from api_server.services.service_api_files import ServiceApiFileService
from api_server.services.service_api_resources import ServiceApiResourceService
from api_server.services.service_api_workflow_logs import (
    ServiceApiWorkflowLogPaginationDict,
    ServiceApiWorkflowLogService,
)
from api_server.services.service_api_workflows import ServiceApiWorkflowRunResponseDict, ServiceApiWorkflowService
from api_server.services.suggested_questions import SuggestedQuestionsService
from api_server.services.task_control import TaskControlService
from configs import dify_config
from core.app.app_config.common.parameters_mapping import AppParametersDict
from graphon.file import helpers as file_helpers
from services.model_provider_service import ModelProviderService

router = APIRouter(tags=["service-api"])


class ServiceApiIndexResponseDict(TypedDict):
    welcome: str
    api_version: str
    server_version: str


class ServiceApiSiteResponseDict(TypedDict):
    title: str
    chat_color_theme: str | None
    chat_color_theme_inverted: bool
    icon_type: str | None
    icon: str | None
    icon_background: str | None
    icon_url: str | None
    description: str | None
    copyright: str | None
    privacy_policy: str | None
    custom_disclaimer: str | None
    default_language: str
    show_workflow_steps: bool
    use_icon_as_answer_icon: bool


class ServiceApiEndUserResponseDict(TypedDict):
    id: str
    tenant_id: str
    app_id: str | None
    type: str
    external_user_id: str | None
    name: str | None
    is_anonymous: bool
    session_id: str
    created_at: str
    updated_at: str


class ServiceApiFileUploadResponseDict(TypedDict):
    id: str
    name: str
    size: int
    extension: str | None
    mime_type: str | None
    created_by: str | None
    created_at: int | None
    url: str


class ServiceApiWorkspaceModelsResponseDict(TypedDict):
    data: list[object]


class ServiceApiMessageFeedbackPayload(BaseModel):
    user: str | None = Field(default=None)
    rating: str | None = Field(default=None)
    content: str | None = Field(default=None)


class ServiceApiConversationRenamePayload(BaseModel):
    user: str | None = Field(default=None)
    name: str | None = Field(default=None)
    auto_generate: bool = Field(default=False)


class ServiceApiCompletionPayload(BaseModel):
    user: str | None = Field(default=None)
    inputs: dict[str, object] = Field(default_factory=dict)
    query: str = Field(default="")
    files: list[dict[str, object]] | None = Field(default=None)
    response_mode: Literal["blocking", "streaming"] | None = Field(default=None)
    retriever_from: str = Field(default="dev")


class ServiceApiChatPayload(BaseModel):
    user: str | None = Field(default=None)
    inputs: dict[str, object] = Field(default_factory=dict)
    query: str
    files: list[dict[str, object]] | None = Field(default=None)
    response_mode: Literal["blocking", "streaming"] | None = Field(default=None)
    conversation_id: str | None = Field(default=None)
    parent_message_id: str | None = Field(default=None)
    retriever_from: str = Field(default="dev")
    auto_generate_name: bool = Field(default=True)
    workflow_id: str | None = Field(default=None)


class ServiceApiWorkflowPayload(BaseModel):
    user: str | None = Field(default=None)
    inputs: dict[str, object] = Field(default_factory=dict)
    files: list[dict[str, object]] | None = Field(default=None)
    response_mode: Literal["blocking", "streaming"] | None = Field(default=None)


class ServiceApiTextToAudioPayload(BaseModel):
    user: str | None = Field(default=None)
    message_id: str | None = Field(default=None)
    voice: str | None = Field(default=None)
    text: str | None = Field(default=None)
    streaming: bool | None = Field(default=None)


class ServiceApiSuggestedQuestionsResponseDict(TypedDict):
    result: str
    data: list[str]


class ServiceApiStopResponseDict(TypedDict):
    result: str


class ServiceApiAudioToTextResponseDict(TypedDict):
    text: str


class ServiceApiFeedbackListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=101)


class ServiceApiWorkflowLogQuery(BaseModel):
    keyword: str | None = None
    status: Literal["succeeded", "failed", "stopped"] | None = None
    created_at__before: str | None = None
    created_at__after: str | None = None
    created_by_end_user_session_id: str | None = None
    created_by_account: str | None = None
    page: int = Field(default=1, ge=1, le=99999)
    limit: int = Field(default=20, ge=1, le=100)


class ServiceApiConversationVariableUpdatePayload(BaseModel):
    user: str | None = Field(default=None)
    value: object


class ServiceApiAnnotationCreatePayload(BaseModel):
    question: str = Field(description="Annotation question")
    answer: str = Field(description="Annotation answer")


class ServiceApiAnnotationReplyActionPayload(BaseModel):
    score_threshold: float = Field(description="Score threshold for annotation matching")
    embedding_provider_name: str = Field(description="Embedding provider name")
    embedding_model_name: str = Field(description="Embedding model name")


def _site_icon_url(site: Site) -> str | None:
    if site.icon and site.icon_type == "image":
        return file_helpers.get_signed_file_url(site.icon)
    return None


def _site_response(site: Site) -> ServiceApiSiteResponseDict:
    return {
        "title": site.title,
        "chat_color_theme": site.chat_color_theme,
        "chat_color_theme_inverted": site.chat_color_theme_inverted,
        "icon_type": site.icon_type,
        "icon": site.icon,
        "icon_background": site.icon_background,
        "icon_url": _site_icon_url(site),
        "description": site.description,
        "copyright": site.copyright,
        "privacy_policy": site.privacy_policy,
        "custom_disclaimer": site.custom_disclaimer,
        "default_language": site.default_language,
        "show_workflow_steps": site.show_workflow_steps,
        "use_icon_as_answer_icon": site.use_icon_as_answer_icon,
    }


def _end_user_response(end_user: EndUser) -> ServiceApiEndUserResponseDict:
    return {
        "id": end_user.id,
        "tenant_id": end_user.tenant_id,
        "app_id": end_user.app_id,
        "type": end_user.type,
        "external_user_id": end_user.external_user_id,
        "name": end_user.name,
        "is_anonymous": end_user.is_anonymous,
        "session_id": end_user.session_id,
        "created_at": end_user.created_at.isoformat(),
        "updated_at": end_user.updated_at.isoformat(),
    }


@router.get("/v1/")
async def get_service_api_index() -> ServiceApiIndexResponseDict:
    return {
        "welcome": "Dify OpenAPI",
        "api_version": "v1",
        "server_version": dify_config.project.version,
    }


@router.get("/v1/workspaces/current/models/model-types/{model_type}")
async def get_service_api_workspace_models(
    request: Request,
    model_type: str,
) -> ServiceApiWorkspaceModelsResponseDict:
    context = await ServiceApiAuthService.resolve_dataset_context(request)
    models = ModelProviderService().get_models_by_model_type(tenant_id=context.tenant.id, model_type=model_type)
    return {"data": [model.model_dump(mode="json") for model in models]}


@router.get("/v1/datasets/{dataset_id}/metadata")
async def get_service_api_dataset_metadata(
    request: Request,
    dataset_id: UUID,
) -> ServiceApiDatasetMetadataResponseDict:
    context = await ServiceApiAuthService.resolve_dataset_context(request)
    return await ServiceApiDatasetMetadataService.get_dataset_metadata(
        tenant_id=context.tenant.id,
        dataset_id=str(dataset_id),
    )


@router.get("/v1/datasets/{dataset_id}/metadata/built-in")
async def get_service_api_dataset_built_in_metadata(
    request: Request,
    dataset_id: UUID,
) -> ServiceApiBuiltInFieldsResponseDict:
    context = await ServiceApiAuthService.resolve_dataset_context(request)
    return await ServiceApiDatasetMetadataService.get_built_in_fields(
        tenant_id=context.tenant.id,
        dataset_id=str(dataset_id),
    )


@router.get("/v1/site")
async def get_service_api_site(request: Request) -> ServiceApiSiteResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    site = await ServiceApiResourceService.get_site(app_id=context.app.id)
    return _site_response(site)


@router.get("/v1/parameters")
async def get_service_api_parameters(request: Request) -> AppParametersDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    return await ServiceApiAppService.get_parameters(app=context.app)


@router.get("/v1/meta")
async def get_service_api_meta(request: Request) -> ToolIconsResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    return await ServiceApiAppService.get_meta(app=context.app)


@router.get("/v1/info")
async def get_service_api_info(request: Request) -> AppInfoResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    return await ServiceApiAppService.get_info(app=context.app)


@router.post("/v1/apps/annotation-reply/{action}")
async def annotation_reply_action(
    request: Request,
    action: Literal["enable", "disable"],
    payload: ServiceApiAnnotationReplyActionPayload,
) -> ServiceApiAnnotationReplyActionResultDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    owner_account = await ServiceApiAuthService.resolve_owner_account(tenant_id=context.tenant.id)
    return ServiceApiAnnotationService.trigger_annotation_reply_action(
        action=action,
        app=context.app,
        tenant_id=context.tenant.id,
        owner_account_id=owner_account.id,
        score_threshold=payload.score_threshold,
        embedding_provider_name=payload.embedding_provider_name,
        embedding_model_name=payload.embedding_model_name,
    )


@router.get("/v1/apps/annotation-reply/{action}/status/{job_id}")
async def annotation_reply_action_status(
    request: Request,
    action: Literal["enable", "disable"],
    job_id: UUID,
) -> ServiceApiAnnotationReplyStatusDict:
    _ = await ServiceApiAuthService.resolve_app_context(request)
    return ServiceApiAnnotationService.get_annotation_reply_action_status(action=action, job_id=str(job_id))


@router.get("/v1/apps/annotations")
async def list_service_api_annotations(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default=""),
) -> ServiceApiAnnotationListDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    return await ServiceApiAnnotationService.list_annotations(
        app_id=context.app.id,
        page=page,
        limit=limit,
        keyword=keyword,
    )


@router.post("/v1/apps/annotations", status_code=201)
async def create_service_api_annotation(
    request: Request,
    payload: ServiceApiAnnotationCreatePayload,
) -> ServiceApiAnnotationDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    owner_account = await ServiceApiAuthService.resolve_owner_account(tenant_id=context.tenant.id)
    return await ServiceApiAnnotationService.create_annotation(
        app=context.app,
        account_id=owner_account.id,
        tenant_id=context.tenant.id,
        question=payload.question,
        answer=payload.answer,
    )


@router.put("/v1/apps/annotations/{annotation_id}")
async def update_service_api_annotation(
    request: Request,
    annotation_id: UUID,
    payload: ServiceApiAnnotationCreatePayload,
) -> ServiceApiAnnotationDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    return await ServiceApiAnnotationService.update_annotation(
        app=context.app,
        tenant_id=context.tenant.id,
        annotation_id=str(annotation_id),
        question=payload.question,
        answer=payload.answer,
    )


@router.delete("/v1/apps/annotations/{annotation_id}", status_code=204, response_model=None)
async def delete_service_api_annotation(
    request: Request,
    annotation_id: UUID,
) -> None:
    context = await ServiceApiAuthService.resolve_app_context(request)
    await ServiceApiAnnotationService.delete_annotation(
        app=context.app,
        tenant_id=context.tenant.id,
        annotation_id=str(annotation_id),
    )


@router.post("/v1/files/upload", status_code=201)
async def upload_service_api_file(
    request: Request,
    file: Annotated[FastAPIUploadFile, FastAPIFile(...)],
    user: str | None = Form(default=None),
) -> ServiceApiFileUploadResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)
    content = await file.read()
    mime_type = file.content_type or "application/octet-stream"
    return await ServiceApiFileService.upload_file(
        app=context.app,
        user=end_user,
        filename=file.filename or "",
        content=content,
        mime_type=mime_type,
    )


@router.post("/v1/audio-to-text")
async def service_api_audio_to_text(
    request: Request,
    file: Annotated[FastAPIUploadFile, FastAPIFile(...)],
    user: str | None = Form(default=None),
) -> ServiceApiAudioToTextResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    content = await file.read()
    result = await PublicAudioService.transcribe_audio(
        context=runtime_context,
        filename=file.filename or "audio",
        content_type=file.content_type or "",
        content=content,
    )
    return {"text": result["text"]}


@router.post("/v1/text-to-audio", response_model=None)
async def service_api_text_to_audio(
    request: Request,
    payload: ServiceApiTextToAudioPayload,
) -> Response | StreamingResponse:
    context = await ServiceApiAuthService.resolve_app_context(request)
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    result = await PublicAudioService.synthesize_audio(
        context=runtime_context,
        text=payload.text,
        voice=payload.voice,
        message_id=payload.message_id,
    )
    if isinstance(result, bytes):
        return Response(content=result, media_type="audio/mpeg")
    return StreamingResponse(result, media_type="audio/mpeg")


@router.get("/v1/files/{file_id}/preview")
async def preview_service_api_file(
    request: Request,
    file_id: str,
    user: str | None = Query(default=None),
    as_attachment: bool = Query(default=False),
) -> FileResponse:
    _ = user
    context = await ServiceApiAuthService.resolve_app_context(request)
    upload_file = await ServiceApiFileService.get_owned_upload_file(app=context.app, file_id=file_id)
    path = ServiceApiFileService.get_file_path(upload_file)
    return _build_file_response(
        path,
        filename=upload_file.name,
        media_type=upload_file.mime_type,
        as_attachment=as_attachment,
    )


@router.post("/v1/completion-messages", response_model=None)
async def create_service_api_completion(
    request: Request,
    payload: ServiceApiCompletionPayload,
) -> JSONResponse | StreamingResponse:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value != "completion":
        raise forbidden(
            "not_completion_app",
            "Please check if your Completion app mode matches the right API route.",
        )
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    response = await AsyncWebGenerationService.run_completion(
        context=runtime_context,
        inputs=payload.inputs,
        query=payload.query,
        files=payload.files,
        streaming=payload.response_mode == "streaming",
    )
    return PublicGenerationBridge.to_fastapi_response(response)


@router.post("/v1/completion-messages/{task_id}/stop")
async def stop_service_api_completion(
    request: Request,
    task_id: str,
    user: str | None = Query(default=None),
) -> ServiceApiStopResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value != "completion":
        raise forbidden(
            "not_completion_app",
            "Please check if your Completion app mode matches the right API route.",
        )
    _ = user
    TaskControlService.stop_task(task_id)
    return {"result": "success"}


@router.post("/v1/chat-messages", response_model=None)
async def create_service_api_chat(
    request: Request,
    payload: ServiceApiChatPayload,
) -> JSONResponse | StreamingResponse:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    response = await AsyncWebGenerationService.run_chat(
        context=runtime_context,
        inputs=payload.inputs,
        query=payload.query,
        files=payload.files,
        conversation_id=payload.conversation_id,
        parent_message_id=payload.parent_message_id,
        streaming=payload.response_mode == "streaming",
    )
    return PublicGenerationBridge.to_fastapi_response(response)


@router.post("/v1/chat-messages/{task_id}/stop")
async def stop_service_api_chat(
    request: Request,
    task_id: str,
    user: str | None = Query(default=None),
) -> ServiceApiStopResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    _ = user
    TaskControlService.stop_task(task_id)
    return {"result": "success"}


@router.post("/v1/workflows/run", response_model=None)
async def create_service_api_workflow(
    request: Request,
    payload: ServiceApiWorkflowPayload,
) -> JSONResponse | StreamingResponse:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value != "workflow":
        raise forbidden("not_workflow_app", "Please check if your Workflow app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    response = await AsyncWebGenerationService.run_workflow(
        context=runtime_context,
        inputs=payload.inputs,
        files=payload.files,
        streaming=payload.response_mode == "streaming",
    )
    return PublicGenerationBridge.to_fastapi_response(response)


@router.post("/v1/workflows/{workflow_id}/run", response_model=None)
async def create_service_api_workflow_by_id(
    request: Request,
    workflow_id: str,
    payload: ServiceApiWorkflowPayload,
) -> JSONResponse | StreamingResponse:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value != "workflow":
        raise forbidden("not_workflow_app", "Please check if your Workflow app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    response = await AsyncWebGenerationService.run_workflow(
        context=runtime_context,
        inputs=payload.inputs,
        files=payload.files,
        streaming=payload.response_mode == "streaming",
        workflow_id=workflow_id,
    )
    return PublicGenerationBridge.to_fastapi_response(response)


@router.get("/v1/workflows/run/{workflow_run_id}")
async def get_service_api_workflow_run(
    request: Request,
    workflow_run_id: str,
) -> ServiceApiWorkflowRunResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"workflow", "advanced-chat"}:
        raise forbidden("not_workflow_app", "Please check if your Workflow app mode matches the right API route.")
    return await ServiceApiWorkflowService.get_workflow_run(
        tenant_id=context.tenant.id,
        app_id=context.app.id,
        workflow_run_id=workflow_run_id,
    )


@router.post("/v1/workflows/tasks/{task_id}/stop")
async def stop_service_api_workflow(
    request: Request,
    task_id: str,
    user: str | None = Query(default=None),
) -> ServiceApiStopResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value != "workflow":
        raise forbidden("not_workflow_app", "Please check if your Workflow app mode matches the right API route.")
    _ = user
    TaskControlService.stop_task(task_id)
    return {"result": "success"}


@router.get("/v1/workflows/logs")
async def list_service_api_workflow_logs(
    request: Request,
    keyword: str | None = Query(default=None),
    status: Literal["succeeded", "failed", "stopped"] | None = Query(default=None),
    created_at__before: str | None = Query(default=None),
    created_at__after: str | None = Query(default=None),
    created_by_end_user_session_id: str | None = Query(default=None),
    created_by_account: str | None = Query(default=None),
    page: int = Query(default=1, ge=1, le=99999),
    limit: int = Query(default=20, ge=1, le=100),
) -> ServiceApiWorkflowLogPaginationDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    created_before = datetime.fromisoformat(created_at__before) if created_at__before else None
    created_after = datetime.fromisoformat(created_at__after) if created_at__after else None
    return await ServiceApiWorkflowLogService.list_logs(
        tenant_id=context.tenant.id,
        app_id=context.app.id,
        keyword=keyword,
        status=status,
        created_at_before=created_before,
        created_at_after=created_after,
        page=page,
        limit=limit,
        created_by_end_user_session_id=created_by_end_user_session_id,
        created_by_account=created_by_account,
    )


@router.get("/v1/messages")
async def list_service_api_messages(
    request: Request,
    conversation_id: str,
    user: str | None = Query(default=None),
    first_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> MessagePaginationDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)

    return await ConversationMessageService.list_messages(
        app_id=context.app.id,
        end_user=end_user,
        conversation_id=conversation_id,
        first_id=first_id,
        limit=limit,
    )


@router.post("/v1/messages/{message_id}/feedbacks")
async def create_service_api_message_feedback(
    request: Request,
    message_id: str,
    payload: ServiceApiMessageFeedbackPayload,
) -> ResultDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)

    return await ConversationMessageService.create_feedback(
        app_id=context.app.id,
        message_id=message_id,
        end_user=end_user,
        rating=payload.rating,
        content=payload.content,
    )


@router.get("/v1/conversations")
async def list_service_api_conversations(
    request: Request,
    user: str | None = Query(default=None),
    last_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    sort_by: Literal["created_at", "-created_at", "updated_at", "-updated_at"] = Query(default="-updated_at"),
) -> ConversationPaginationDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)
    return await ConversationMessageService.list_conversations(
        app_id=context.app.id,
        end_user=end_user,
        last_id=last_id,
        limit=limit,
        pinned=None,
        sort_by=sort_by,
    )


@router.delete("/v1/conversations/{conversation_id}", status_code=204, response_model=None)
async def delete_service_api_conversation(
    request: Request,
    conversation_id: str,
    user: str | None = Query(default=None),
) -> None:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)
    await ConversationMessageService.delete_conversation(
        app_id=context.app.id,
        conversation_id=conversation_id,
        end_user=end_user,
    )


@router.post("/v1/conversations/{conversation_id}/name")
async def rename_service_api_conversation(
    request: Request,
    conversation_id: str,
    payload: ServiceApiConversationRenamePayload,
) -> ConversationItemDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    return await ConversationMessageService.rename_conversation(
        app_id=context.app.id,
        conversation_id=conversation_id,
        end_user=end_user,
        name=payload.name,
        auto_generate=payload.auto_generate,
    )


@router.get("/v1/conversations/{conversation_id}/variables")
async def list_service_api_conversation_variables(
    request: Request,
    conversation_id: str,
    user: str | None = Query(default=None),
    last_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    variable_name: str | None = Query(default=None, min_length=1, max_length=255),
) -> ServiceApiConversationVariablePaginationDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)
    return await ServiceApiConversationVariableService.list_variables(
        app=context.app,
        conversation_id=conversation_id,
        end_user=end_user,
        limit=limit,
        last_id=last_id,
        variable_name=variable_name,
    )


@router.put("/v1/conversations/{conversation_id}/variables/{variable_id}")
async def update_service_api_conversation_variable(
    request: Request,
    conversation_id: str,
    variable_id: str,
    payload: ServiceApiConversationVariableUpdatePayload,
) -> ServiceApiConversationVariableDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=payload.user)
    return await ServiceApiConversationVariableService.update_variable(
        app=context.app,
        conversation_id=conversation_id,
        variable_id=variable_id,
        end_user=end_user,
        value=payload.value,
    )


@router.get("/v1/messages/{message_id}/suggested")
async def get_service_api_suggested_questions(
    request: Request,
    message_id: str,
    user: str = Query(...),
) -> ServiceApiSuggestedQuestionsResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    if context.app.mode.value not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    end_user = await ServiceApiAuthService.resolve_end_user(app=context.app, user_id=user)
    runtime_context = await ServiceApiResourceService.build_runtime_context(app=context.app, end_user=end_user)
    questions = await SuggestedQuestionsService.get_suggested_questions(context=runtime_context, message_id=message_id)
    return {"result": "success", "data": questions}


@router.get("/v1/app/feedbacks")
async def list_service_api_feedbacks(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=101),
) -> ServiceApiFeedbackListResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    return await ServiceApiFeedbackService.list_feedbacks(app_id=context.app.id, page=page, limit=limit)


@router.get("/v1/end-users/{end_user_id}")
async def get_service_api_end_user(
    request: Request,
    end_user_id: UUID,
) -> ServiceApiEndUserResponseDict:
    context = await ServiceApiAuthService.resolve_app_context(request)
    end_user = await ServiceApiResourceService.get_end_user(
        tenant_id=context.tenant.id,
        app_id=context.app.id,
        end_user_id=str(end_user_id),
    )
    return _end_user_response(end_user)
