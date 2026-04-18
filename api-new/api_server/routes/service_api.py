"""FastAPI service API routes."""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from fastapi import APIRouter, Request

from api_server.models.app import EndUser, Site
from api_server.services.service_api_auth import ServiceApiAuthService
from api_server.services.service_api_resources import ServiceApiResourceService
from configs import dify_config
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
