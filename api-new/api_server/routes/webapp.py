from __future__ import annotations

import json
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, NotRequired, TypedDict

import httpx
from fastapi import APIRouter, Query, Request
from fastapi import File as FastAPIFile
from fastapi import UploadFile as FastAPIUploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from api_server.auth import extract_webapp_access_token, verify_passport
from api_server.errors import forbidden, unauthorized
from api_server.models.app import ApiToolProvider, App, EndUser, Site
from api_server.services.app_lookup import AppLookupService
from api_server.services.file_upload import FileUploadService, UploadedFileResponseDict
from api_server.services.webapp_context import WebappContextService
from api_server.services.webapp_login import WebappLoginService, WebappResetPasswordService
from configs import dify_config
from core.app.app_config.common.parameters_mapping import AppParametersDict, get_parameters_from_feature_dict
from extensions.ext_database import db
from libs.password import valid_password
from services.enterprise.enterprise_service import EnterpriseService

router = APIRouter(tags=["webapp"])


class SitePayloadDict(TypedDict):
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
    prompt_public: bool
    show_workflow_steps: bool
    use_icon_as_answer_icon: bool


class WebappCustomConfigDict(TypedDict):
    remove_webapp_brand: bool
    replace_webapp_logo: str | None


class AppSiteResponseDict(TypedDict):
    app_id: str
    end_user_id: str
    enable_site: bool
    site: SitePayloadDict
    model_config: None
    plan: str
    can_replace_logo: bool
    custom_config: WebappCustomConfigDict | None


class ToolIconMapDict(TypedDict):
    tool_icons: dict[str, Any]


class WebappPermissionResponseDict(TypedDict):
    result: bool


class LoginStatusResponseDict(TypedDict):
    logged_in: bool
    app_logged_in: bool


class PassportResponseDict(TypedDict):
    access_token: str


class LogoutResponseDict(TypedDict):
    result: str


class LoginSuccessDataDict(TypedDict):
    access_token: str


class LoginResponseDict(TypedDict):
    result: str
    data: LoginSuccessDataDict


class RemoteFileInfoResponseDict(TypedDict):
    file_type: str
    file_length: int


class FileUploadResponseDict(TypedDict):
    id: str
    name: str
    size: int
    extension: str | None
    mime_type: str | None
    created_by: str | None
    created_at: int | None


class EmailCodeLoginSendResponseDict(TypedDict):
    result: str
    data: str


class ForgotPasswordValidityResponseDict(TypedDict):
    is_valid: bool
    email: str
    token: str


class WebappAccessTokenPayloadDict(TypedDict):
    user_id: NotRequired[str]
    session_id: NotRequired[str]
    auth_type: NotRequired[str]
    token_source: NotRequired[str]
    exp: NotRequired[int]


class LoginPayload(BaseModel):
    email: str = Field(description="User email address")
    password: str = Field(description="User password")

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return valid_password(value)


class EmailCodeLoginSendPayload(BaseModel):
    email: str = Field(description="User email address")
    language: str | None = Field(default=None, description="Email language")


class EmailCodeLoginVerifyPayload(BaseModel):
    email: str = Field(description="User email address")
    code: str = Field(description="Verification code")
    token: str = Field(min_length=1, description="Signed email code token")


class ForgotPasswordSendPayload(BaseModel):
    email: str = Field(description="User email address")
    language: str | None = Field(default=None, description="Email language")


class ForgotPasswordCheckPayload(BaseModel):
    email: str = Field(description="User email address")
    code: str = Field(description="Verification code")
    token: str = Field(min_length=1, description="Signed reset-password token")


class ForgotPasswordResetPayload(BaseModel):
    token: str = Field(min_length=1, description="Signed reset-password token")
    new_password: str = Field(description="New password")
    password_confirm: str = Field(description="Repeated password")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return valid_password(value)


class RemoteFileUploadPayload(BaseModel):
    url: str = Field(description="Remote file URL")


@router.get("/api/site")
async def get_site(request: Request) -> AppSiteResponseDict:
    context = await WebappContextService.resolve(request)
    if context.tenant.status == context.tenant.status.ARCHIVE:
        raise forbidden("not_found", "Site is disabled.")

    can_replace_logo = bool(getattr(dify_config, "CAN_REPLACE_LOGO", False))
    custom_config: WebappCustomConfigDict | None = None
    if can_replace_logo:
        base_url = dify_config.FILES_URL
        remove_webapp_brand = context.tenant.custom_config_dict.get("remove_webapp_brand", False)
        replace_webapp_logo = (
            f"{base_url}/files/workspaces/{context.tenant.id}/webapp-logo"
            if context.tenant.custom_config_dict.get("replace_webapp_logo")
            else None
        )
        custom_config = {
            "remove_webapp_brand": remove_webapp_brand,
            "replace_webapp_logo": replace_webapp_logo,
        }

    return {
        "app_id": context.app.id,
        "end_user_id": context.end_user.id,
        "enable_site": context.app.enable_site,
        "site": {
            "title": context.site.title,
            "chat_color_theme": context.site.chat_color_theme,
            "chat_color_theme_inverted": context.site.chat_color_theme_inverted,
            "icon_type": context.site.icon_type,
            "icon": context.site.icon,
            "icon_background": context.site.icon_background,
            "icon_url": None,
            "description": context.site.description,
            "copyright": context.site.copyright,
            "privacy_policy": context.site.privacy_policy,
            "custom_disclaimer": context.site.custom_disclaimer,
            "default_language": context.site.default_language,
            "prompt_public": context.site.prompt_public,
            "show_workflow_steps": context.site.show_workflow_steps,
            "use_icon_as_answer_icon": context.site.use_icon_as_answer_icon,
        },
        "model_config": None,
        "plan": context.tenant.plan,
        "can_replace_logo": can_replace_logo,
        "custom_config": custom_config,
    }


@router.get("/api/parameters")
async def get_parameters(request: Request) -> AppParametersDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode in {"advanced-chat", "workflow"}:
        if context.workflow is None:
            raise forbidden("app_unavailable", "App unavailable, please check your app configurations.")
        features_dict = context.workflow.features_dict
        user_input_form = context.workflow.user_input_form(to_old_structure=True)
    else:
        if context.app_model_config is None:
            raise forbidden("app_unavailable", "App unavailable, please check your app configurations.")
        features_dict = context.app_model_config.to_feature_dict()
        user_input_form = features_dict.get("user_input_form", [])

    return get_parameters_from_feature_dict(features_dict=features_dict, user_input_form=user_input_form)


@router.get("/api/meta")
async def get_meta(request: Request) -> ToolIconMapDict:
    context = await WebappContextService.resolve(request)
    meta: ToolIconMapDict = {"tool_icons": {}}

    tools: list[dict[str, Any]]
    if context.app.mode in {"advanced-chat", "workflow"}:
        if context.workflow is None:
            return meta
        nodes = context.workflow.graph_dict.get("nodes", [])
        tools = []
        for node in nodes:
            node_data = node.get("data", {})
            if node_data.get("type") == "tool":
                tools.append(
                    {
                        "provider_type": node_data.get("provider_type"),
                        "provider_id": node_data.get("provider_id"),
                        "tool_name": node_data.get("tool_name"),
                        "tool_parameters": {},
                    }
                )
    else:
        if context.app_model_config is None:
            return meta
        tools = list(context.app_model_config.to_feature_dict().get("agent_mode", {}).get("tools", []))

    url_prefix = dify_config.CONSOLE_API_URL + "/console/api/workspaces/current/tool-provider/builtin/"
    async with db.session_context() as session:
        for tool in tools:
            if len(list(tool.keys())) < 4:
                continue
            provider_type = tool.get("provider_type", "")
            provider_id = tool.get("provider_id", "")
            tool_name = tool.get("tool_name", "")
            if provider_type == "builtin":
                meta["tool_icons"][tool_name] = url_prefix + provider_id + "/icon"
            elif provider_type == "api":
                provider = await session.scalar(select(ApiToolProvider).where(ApiToolProvider.id == provider_id).limit(1))
                if provider is None:
                    meta["tool_icons"][tool_name] = {"background": "#252525", "content": "\ud83d\ude01"}
                else:
                    try:
                        meta["tool_icons"][tool_name] = json.loads(provider.icon)
                    except Exception:
                        meta["tool_icons"][tool_name] = {"background": "#252525", "content": "\ud83d\ude01"}

    return meta


@router.get("/api/remote-files/{url:path}")
async def get_remote_file_info(request: Request, url: str) -> RemoteFileInfoResponseDict:
    _ = await WebappContextService.resolve(request)
    decoded_url = urllib.parse.unquote(url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=10.0, connect=3.0)) as client:
        response = await client.head(decoded_url)
        if response.status_code != httpx.codes.OK:
            response = await client.get(decoded_url, timeout=3)
    response.raise_for_status()
    return {
        "file_type": response.headers.get("Content-Type", "application/octet-stream"),
        "file_length": int(response.headers.get("Content-Length", -1)),
    }


@router.post("/api/remote-files/upload")
async def upload_remote_file(
    request: Request,
    payload: RemoteFileUploadPayload,
) -> UploadedFileResponseDict:
    context = await WebappContextService.resolve(request)
    url = str(payload.url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=10.0, connect=3.0)) as client:
        response = await client.head(url)
        if response.status_code != httpx.codes.OK:
            response = await client.get(url, timeout=3, follow_redirects=True)
        response.raise_for_status()
        content = response.content if response.request.method == "GET" else (await client.get(url)).content

    filename = url.rstrip("/").split("/")[-1] or "download.bin"
    mimetype = response.headers.get("Content-Type", "application/octet-stream")
    return await FileUploadService.upload_file(
        filename=filename,
        content=content,
        mimetype=mimetype,
        user=context.end_user,
        source_url=url,
    )


@router.post("/api/files/upload")
async def upload_file(
    request: Request,
    file: FastAPIUploadFile = FastAPIFile(...),
) -> FileUploadResponseDict:
    context = await WebappContextService.resolve(request)
    content = await file.read()
    uploaded = await FileUploadService.upload_file(
        filename=file.filename or "",
        content=content,
        mimetype=file.content_type or "application/octet-stream",
        user=context.end_user,
    )
    return {
        "id": uploaded["id"],
        "name": uploaded["name"],
        "size": uploaded["size"],
        "extension": uploaded["extension"],
        "mime_type": uploaded["mime_type"],
        "created_by": uploaded["created_by"],
        "created_at": uploaded["created_at"],
    }


@router.get("/api/passport")
async def get_passport(
    request: Request,
    user_id: str | None = Query(default=None, description="Optional browser session identifier"),
) -> PassportResponseDict:
    app_code = request.headers.get("X-App-Code")
    if not app_code:
        raise unauthorized("missing_app_code", "X-App-Code header is missing.")

    access_token = extract_webapp_access_token(request)
    enterprise_payload = _decode_webapp_access_token(access_token) if access_token else None

    if bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        access_mode = EnterpriseService.WebAppAuth.get_app_access_mode_by_id(await AppLookupService.get_app_id_by_code(app_code))
        if access_mode.access_mode != "public":
            if enterprise_payload is None:
                raise unauthorized("web_sso_auth_required", "Web app authentication required.")
            return await _issue_authenticated_passport(app_code=app_code, enterprise_payload=enterprise_payload)

    return await _issue_public_passport(app_code=app_code, user_id=user_id)


@router.get("/api/login/status")
async def get_login_status(
    request: Request,
    app_code: str | None = Query(default=None, description="Application code"),
    user_id: str | None = Query(default=None, description="Browser session identifier"),
) -> LoginStatusResponseDict:
    token = extract_webapp_access_token(request)
    if not app_code:
        return {"logged_in": bool(token), "app_logged_in": False}

    access_mode = "public"
    if bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        app_id = await AppLookupService.get_app_id_by_code(app_code)
        access_mode = EnterpriseService.WebAppAuth.get_app_access_mode_by_id(app_id).access_mode

    user_logged_in = access_mode == "public"
    if not user_logged_in and token:
        user_logged_in = _decode_webapp_access_token(token) is not None

    app_logged_in = False
    try:
        fake_headers = dict(request.headers)
        fake_headers["X-App-Code"] = app_code
        scope = dict(request.scope)
        scope["headers"] = [(k.lower().encode(), v.encode()) for k, v in fake_headers.items()]
        scoped_request = Request(scope, receive=request.receive)
        _ = await WebappContextService.resolve(scoped_request, expected_user_id=user_id)
        app_logged_in = True
    except Exception:
        app_logged_in = False

    return {"logged_in": user_logged_in, "app_logged_in": app_logged_in}


@router.post("/api/logout")
async def logout() -> LogoutResponseDict:
    return {"result": "success"}


@router.post("/api/login")
async def login(payload: LoginPayload) -> LoginResponseDict:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        raise unauthorized("authentication_failed", "Authentication failed.")

    account = await WebappLoginService.authenticate(payload.email, payload.password)
    token = WebappLoginService.issue_access_token(account)
    return {"result": "success", "data": {"access_token": token}}


@router.post("/api/email-code-login")
async def send_email_code_login(payload: EmailCodeLoginSendPayload) -> EmailCodeLoginSendResponseDict:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        raise unauthorized("authentication_failed", "Authentication failed.")

    _ = await WebappLoginService.get_user_by_email(payload.email)
    _code, token = WebappLoginService.issue_email_code(payload.email)
    return {"result": "success", "data": token}


@router.post("/api/email-code-login/validity")
async def verify_email_code_login(payload: EmailCodeLoginVerifyPayload) -> LoginResponseDict:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        raise unauthorized("authentication_failed", "Authentication failed.")

    token_payload = WebappLoginService.verify_email_code_token(payload.token)
    normalized_email = payload.email.lower()
    if token_payload["email"] != normalized_email:
        raise unauthorized("invalid_email", "Invalid email.")
    if token_payload["code"] != payload.code:
        raise unauthorized("invalid_email_code", "Invalid email code.")

    account = await WebappLoginService.get_user_by_email(normalized_email)
    token = WebappLoginService.issue_access_token(account)
    return {"result": "success", "data": {"access_token": token}}


@router.post("/api/forgot-password")
async def send_forgot_password(payload: ForgotPasswordSendPayload) -> EmailCodeLoginSendResponseDict:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        raise unauthorized("authentication_failed", "Authentication failed.")

    _ = await WebappLoginService.get_user_by_email(payload.email)
    _code, token = WebappResetPasswordService.issue_reset_password_code(payload.email)
    return {"result": "success", "data": token}


@router.post("/api/forgot-password/validity")
async def check_forgot_password(payload: ForgotPasswordCheckPayload) -> ForgotPasswordValidityResponseDict:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        raise unauthorized("authentication_failed", "Authentication failed.")

    normalized_email = payload.email.lower()
    token_payload = WebappResetPasswordService.verify_reset_password_token(payload.token)
    if token_payload["email"] != normalized_email:
        raise unauthorized("invalid_email", "Invalid email.")
    if token_payload["code"] != payload.code:
        raise unauthorized("invalid_email_code", "Invalid email code.")

    refreshed_token = WebappResetPasswordService.issue_reset_password_token(
        email=normalized_email,
        code=payload.code,
        phase="reset",
    )
    return {"is_valid": True, "email": normalized_email, "token": refreshed_token}


@router.post("/api/forgot-password/resets")
async def reset_forgot_password(payload: ForgotPasswordResetPayload) -> LogoutResponseDict:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        raise unauthorized("authentication_failed", "Authentication failed.")
    if payload.new_password != payload.password_confirm:
        raise unauthorized("password_mismatch", "Passwords do not match.")

    token_payload = WebappResetPasswordService.verify_reset_password_token(payload.token)
    if token_payload["phase"] != "reset":
        raise unauthorized("invalid_token", "Invalid token.")

    await WebappResetPasswordService.update_password(email=token_payload["email"], new_password=payload.new_password)
    return {"result": "success"}


def _decode_webapp_access_token(token: str) -> WebappAccessTokenPayloadDict | None:
    try:
        decoded = verify_passport(token)
    except Exception:
        return None

    payload: WebappAccessTokenPayloadDict = {}
    user_id = decoded.get("user_id")
    if isinstance(user_id, str):
        payload["user_id"] = user_id
    session_id = decoded.get("session_id")
    if isinstance(session_id, str):
        payload["session_id"] = session_id
    auth_type = decoded.get("auth_type")
    if isinstance(auth_type, str):
        payload["auth_type"] = auth_type
    token_source = decoded.get("token_source")
    if isinstance(token_source, str):
        payload["token_source"] = token_source
    exp = decoded.get("exp")
    if isinstance(exp, int):
        payload["exp"] = exp

    source = payload.get("token_source")
    if source != "webapp_login_token":
        return None
    return payload


async def _issue_public_passport(app_code: str, user_id: str | None) -> PassportResponseDict:
    async with db.session_context() as session:
        site = await session.scalar(select(Site).where(Site.code == app_code, Site.status == "normal").limit(1))
        if site is None:
            raise forbidden("not_found", "App not found.")

        app = await session.scalar(select(App).where(App.id == site.app_id).limit(1))
        if app is None or app.status != "normal" or not app.enable_site:
            raise forbidden("not_found", "App not found.")

        end_user: EndUser | None = None
        if user_id:
            end_user = await session.scalar(
                select(EndUser).where(EndUser.app_id == app.id, EndUser.session_id == user_id).limit(1)
            )

        if end_user is None:
            session_id = user_id or await _generate_session_id(session)
            end_user = EndUser(
                tenant_id=app.tenant_id,
                app_id=app.id,
                type="browser",
                session_id=session_id,
            )
            async with session.begin():
                session.add(end_user)
                await session.flush()

        payload = {
            "iss": site.app_id,
            "sub": "Web API Passport",
            "app_id": site.app_id,
            "app_code": app_code,
            "end_user_id": end_user.id,
        }

    return {"access_token": _issue_token(payload)}


async def _issue_authenticated_passport(
    *,
    app_code: str,
    enterprise_payload: WebappAccessTokenPayloadDict,
) -> PassportResponseDict:
    async with db.session_context() as session:
        site = await session.scalar(select(Site).where(Site.code == app_code, Site.status == "normal").limit(1))
        if site is None:
            raise forbidden("not_found", "App not found.")

        app = await session.scalar(select(App).where(App.id == site.app_id).limit(1))
        if app is None or app.status != "normal" or not app.enable_site:
            raise forbidden("not_found", "App not found.")

        session_id = enterprise_payload.get("session_id")
        end_user: EndUser | None = None
        if isinstance(session_id, str):
            end_user = await session.scalar(
                select(EndUser).where(
                    EndUser.session_id == session_id,
                    EndUser.tenant_id == app.tenant_id,
                    EndUser.app_id == app.id,
                ).limit(1)
            )
        if end_user is None:
            end_user = EndUser(
                tenant_id=app.tenant_id,
                app_id=app.id,
                type="browser",
                session_id=session_id or await _generate_session_id(session),
            )
            async with session.begin():
                session.add(end_user)
                await session.flush()

        exp = enterprise_payload.get("exp")
        expiry = int(exp) if isinstance(exp, int) else int(
            (datetime.now(UTC) + timedelta(minutes=dify_config.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()
        )

        payload = {
            "iss": site.id,
            "sub": "Web API Passport",
            "app_id": site.app_id,
            "app_code": site.code,
            "user_id": enterprise_payload.get("user_id"),
            "end_user_id": end_user.id,
            "auth_type": enterprise_payload.get("auth_type"),
            "granted_at": int(datetime.now(UTC).timestamp()),
            "token_source": "webapp",
            "exp": expiry,
        }

    return {"access_token": _issue_token(payload)}


async def _generate_session_id(session) -> str:
    while True:
        session_id = str(uuid.uuid4())
        existing_count = await session.scalar(select(func.count()).select_from(EndUser).where(EndUser.session_id == session_id))
        if int(existing_count or 0) == 0:
            return session_id


def _issue_token(payload: dict[str, Any]) -> str:
    import jwt

    return jwt.encode(payload, dify_config.SECRET_KEY, algorithm="HS256")
