"""FastAPI service API routes."""

from __future__ import annotations

from typing import Annotated, TypedDict
from uuid import UUID

from fastapi import APIRouter, Form, Query, Request
from fastapi import File as FastAPIFile
from fastapi import UploadFile as FastAPIUploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api_server.errors import forbidden
from api_server.models.app import EndUser, Site
from api_server.routes.files import _build_file_response
from api_server.services.conversation_message import ConversationMessageService, MessagePaginationDict, ResultDict
from api_server.services.service_api_apps import AppInfoResponseDict, ServiceApiAppService, ToolIconsResponseDict
from api_server.services.service_api_auth import ServiceApiAuthService
from api_server.services.service_api_files import ServiceApiFileService
from api_server.services.service_api_resources import ServiceApiResourceService
from api_server.services.suggested_questions import SuggestedQuestionsService
from configs import dify_config
from core.app.app_config.common.parameters_mapping import AppParametersDict
from graphon.file import helpers as file_helpers

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


class ServiceApiMessageFeedbackPayload(BaseModel):
    user: str | None = Field(default=None)
    rating: str | None = Field(default=None)
    content: str | None = Field(default=None)


class ServiceApiSuggestedQuestionsResponseDict(TypedDict):
    result: str
    data: list[str]


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
