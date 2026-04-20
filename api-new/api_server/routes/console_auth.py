"""FastAPI migration for the legacy console auth/session surface.

This module preserves the externally visible console auth contracts while
moving the route boundary off Flask. The underlying account and OAuth services
are still largely sync today, so the FastAPI handlers isolate those calls behind
`asyncio.to_thread(...)` until the service layer itself is ported.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, NotRequired, TypedDict, cast
from uuid import UUID

import httpx
import libs.oauth_data_source as oauth_data_source_lib
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from api_server.errors import ApiError, forbidden, unauthorized
from api_server.routes.console_misc import _ensure_console_setup
from configs import dify_config
from constants import (
    COOKIE_NAME_ACCESS_TOKEN,
    COOKIE_NAME_CSRF_TOKEN,
    COOKIE_NAME_REFRESH_TOKEN,
    HEADER_NAME_CSRF_TOKEN,
)
from constants.languages import get_valid_language, languages, supported_language
from core.db.session_factory import get_sync_session_maker
from events.tenant_event import tenant_was_created
from extensions.ext_database import db
from libs.datetime_utils import naive_utc_now
from libs.encryption import FieldEncryption
from libs.exception import BaseHTTPException
from libs.helper import EmailStr, timezone
from libs.oauth import GitHubOAuth, GoogleOAuth, OAuthUserInfo
from libs.oauth_data_source import NOTION_SOURCE_INFO_ADAPTER, SOURCE_INFO_STORAGE_ADAPTER, NotionOAuth
from libs.passport import PassportService
from libs.password import hash_password, valid_password
from libs.token import CSRF_WHITE_LIST, _cookie_domain, _real_cookie_name, is_secure
from models import Account, AccountStatus
from models.source import DataSourceOauthBinding
from services.account_service import AccountService, InvitationDetailDict, RegisterService, TenantService, TokenPair
from services.auth.api_key_auth_service import ApiKeyAuthService
from services.billing_service import BillingService
from services.entities.auth_entities import (
    ForgotPasswordCheckPayload,
    ForgotPasswordResetPayload,
    ForgotPasswordSendPayload,
    LoginFailureReason,
    LoginPayloadBase,
)
from services.errors.account import AccountRegisterError
from services.errors.workspace import WorkSpaceNotAllowedCreateError, WorkSpaceNotFoundError
from services.feature_service import FeatureService
from services.oauth_server import OAUTH_ACCESS_TOKEN_EXPIRES_IN, OAuthGrantType, OAuthServerService

router = APIRouter(tags=["console"])
logger = logging.getLogger(__name__)

_EN_US = "en-US"


class LoginPayload(LoginPayloadBase):
    model_config = ConfigDict(extra="forbid")

    remember_me: bool = Field(default=False)
    invite_token: str | None = Field(default=None)


class EmailPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(...)
    language: str | None = Field(default=None)


class EmailCodeLoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(...)
    code: str = Field(...)
    token: str = Field(...)
    language: str | None = Field(default=None)


class EmailRegisterSendPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(...)
    language: str | None = Field(default=None)


class EmailRegisterValidityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(...)
    code: str = Field(...)
    token: str = Field(...)


class EmailRegisterResetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(...)
    new_password: str = Field(...)
    password_confirm: str = Field(...)

    @field_validator("new_password", "password_confirm")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return valid_password(value)


class ActivateCheckQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = Field(default=None)
    email: EmailStr | None = Field(default=None)
    token: str = Field(...)


class ActivatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = Field(default=None)
    email: EmailStr | None = Field(default=None)
    token: str = Field(...)
    name: str = Field(..., max_length=30)
    interface_language: str = Field(...)
    timezone: str = Field(...)

    @field_validator("interface_language")
    @classmethod
    def validate_lang(cls, value: str) -> str:
        return supported_language(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return timezone(value)


class OAuthClientPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(...)


class OAuthProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(...)
    redirect_uri: str = Field(...)


class OAuthTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(...)
    grant_type: str = Field(...)
    code: str | None = Field(default=None)
    client_secret: str | None = Field(default=None)
    redirect_uri: str | None = Field(default=None)
    refresh_token: str | None = Field(default=None)


class ApiKeyAuthBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(...)
    provider: str = Field(...)
    credentials: dict[str, object] = Field(...)


class ResultSuccessResponse(TypedDict):
    result: Literal["success"]


class ResultSuccessWithDataResponse(TypedDict):
    result: Literal["success"]
    data: str


class ResultSuccessWithTokenDataResponse(TypedDict):
    result: Literal["success"]
    data: dict[str, str]


class ResultFailMessageResponse(TypedDict):
    result: Literal["fail"]
    message: str


class ResultFailDataResponse(TypedDict):
    result: Literal["fail"]
    data: str


class ValidityResponse(TypedDict):
    is_valid: bool
    email: str
    token: str


class ActivationCheckData(TypedDict):
    workspace_name: str | None
    workspace_id: str | None
    email: str | None


class ActivationCheckResponse(TypedDict):
    is_valid: bool
    data: NotRequired[ActivationCheckData]


class OAuthProviderInfoResponse(TypedDict):
    app_icon: str | None
    app_label: str
    scope: str | None


class OAuthAuthorizeCodeResponse(TypedDict):
    code: str


class OAuthTokenResponse(TypedDict):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: int
    refresh_token: str


class OAuthAccountResponse(TypedDict):
    name: str
    email: str
    avatar: str | None
    interface_language: str | None
    timezone: str | None


class ErrorResponse(TypedDict):
    error: str


class OAuthDataSourceResponse(TypedDict):
    data: str


class OAuthSourceBindingResponse(TypedDict):
    result: Literal["success"]


class ApiKeySourceItem(TypedDict):
    id: str
    category: str
    provider: str
    disabled: bool
    created_at: int
    updated_at: int


class ApiKeySourceListResponse(TypedDict):
    sources: list[ApiKeySourceItem]


def _api_error_from_legacy(exc: BaseHTTPException) -> ApiError:
    return ApiError(
        status_code=int(exc.code),
        code=exc.error_code,
        message=str(exc.description or ""),
    )


def _legacy_error(status_code: int, code: str, message: str) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=message)


def _invalid_email_error() -> ApiError:
    return _legacy_error(400, "invalid_email", "The email address is not valid.")


def _invalid_token_error() -> ApiError:
    return _legacy_error(400, "invalid_or_expired_token", "The token is invalid or has expired.")


def _email_code_error(message: str = "Email code is invalid or expired.") -> ApiError:
    return _legacy_error(400, "email_code_error", message)


def _authentication_failed_error(message: str = "Invalid email or password.") -> ApiError:
    return _legacy_error(401, "authentication_failed", message)


def _password_mismatch_error() -> ApiError:
    return _legacy_error(400, "password_mismatch", "The passwords do not match.")


def _email_already_in_use_error() -> ApiError:
    return _legacy_error(400, "email_already_in_use", "A user with this email already exists.")


def _account_banned_error() -> ApiError:
    return _legacy_error(400, "account_banned", "Account is banned.")


def _account_in_freeze_error() -> ApiError:
    return _legacy_error(
        400,
        "account_in_freeze",
        "This email account has been deleted within the past 30 days and is temporarily unavailable for new account registration.",
    )


def _email_send_ip_limit_error() -> ApiError:
    return _legacy_error(
        429,
        "email_send_ip_limit",
        "Too many emails have been sent from this IP address recently. Please try again later.",
    )


def _email_password_login_limit_error() -> ApiError:
    return _legacy_error(
        429,
        "email_code_login_limit",
        "Too many incorrect password attempts. Please try again later.",
    )


def _email_password_reset_limit_error() -> ApiError:
    return _legacy_error(
        429,
        "email_password_reset_limit",
        "Too many failed password reset attempts. Please try again in 24 hours.",
    )


def _email_register_limit_error() -> ApiError:
    return _legacy_error(
        429,
        "email_register_limit",
        "Too many failed email register attempts. Please try again in 24 hours.",
    )


def _workspaces_limit_exceeded_error() -> ApiError:
    return _legacy_error(
        400,
        "limit_exceeded",
        "Unable to create workspace because the maximum workspace limit was exceeded",
    )


def _not_allowed_create_workspace_error() -> ApiError:
    return _legacy_error(
        400,
        "not_allowed_create_workspace",
        "Workspace not found, please contact system admin to invite you to join in a workspace.",
    )


def _account_not_initialized_error() -> ApiError:
    return _legacy_error(
        400,
        "account_not_initialized",
        "The account has not been initialized yet. Please proceed with the initialization process first.",
    )


def _already_activate_error() -> ApiError:
    return _legacy_error(
        403,
        "already_activate",
        "Auth Token is invalid or account already activated, please check again.",
    )


def _account_not_found_error() -> ApiError:
    return _legacy_error(400, "account_not_found", "Account not found.")


def _api_key_auth_failed_error(message: str) -> ApiError:
    return _legacy_error(500, "auth_failed", message)


def _extract_remote_ip(request: Request) -> str:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    client = request.client
    return client.host if client else ""


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if not auth_header or " " not in auth_header:
        return None
    auth_scheme, auth_token = auth_header.split(None, 1)
    if auth_scheme.lower() != "bearer":
        return None
    return auth_token


def _extract_access_token(request: Request) -> str | None:
    return request.cookies.get(_real_cookie_name(COOKIE_NAME_ACCESS_TOKEN)) or _extract_bearer_token(request)


def _extract_refresh_token(request: Request) -> str | None:
    return request.cookies.get(_real_cookie_name(COOKIE_NAME_REFRESH_TOKEN))


def _extract_csrf_token(request: Request) -> str | None:
    return request.headers.get(HEADER_NAME_CSRF_TOKEN)


def _extract_csrf_cookie(request: Request) -> str | None:
    return request.cookies.get(_real_cookie_name(COOKIE_NAME_CSRF_TOKEN))


def _set_cookie(
    response: Response,
    *,
    cookie_name: str,
    value: str,
    max_age: int,
    http_only: bool,
    samesite: Literal["lax", "none", "strict"] = "lax",
) -> None:
    response.set_cookie(
        _real_cookie_name(cookie_name),
        value=value,
        httponly=http_only,
        domain=_cookie_domain(),
        secure=is_secure(),
        samesite=samesite,
        max_age=max_age,
        path="/",
    )

def _clear_cookie(
    response: Response,
    *,
    cookie_name: str,
    http_only: bool,
    samesite: Literal["lax", "none", "strict"] = "lax",
) -> None:
    response.set_cookie(
        _real_cookie_name(cookie_name),
        "",
        expires=0,
        path="/",
        domain=_cookie_domain(),
        secure=is_secure(),
        httponly=http_only,
        samesite=samesite,
    )


def _set_auth_cookies(response: Response, token_pair: TokenPair) -> None:
    _set_cookie(
        response,
        cookie_name=COOKIE_NAME_ACCESS_TOKEN,
        value=token_pair.access_token,
        http_only=True,
        max_age=int(dify_config.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
    )
    _set_cookie(
        response,
        cookie_name=COOKIE_NAME_REFRESH_TOKEN,
        value=token_pair.refresh_token,
        http_only=True,
        max_age=int(60 * 60 * 24 * dify_config.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    _set_cookie(
        response,
        cookie_name=COOKIE_NAME_CSRF_TOKEN,
        value=token_pair.csrf_token,
        http_only=False,
        max_age=int(60 * dify_config.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def _clear_auth_cookies(response: Response) -> None:
    _clear_cookie(response, cookie_name=COOKIE_NAME_ACCESS_TOKEN, http_only=True)
    _clear_cookie(response, cookie_name=COOKIE_NAME_REFRESH_TOKEN, http_only=True)
    _clear_cookie(response, cookie_name=COOKIE_NAME_CSRF_TOKEN, http_only=False)


def _validate_csrf(request: Request, user_id: str) -> None:
    auth_token = _extract_access_token(request)
    if dify_config.ADMIN_API_KEY_ENABLE and auth_token and auth_token == dify_config.ADMIN_API_KEY:
        return

    for pattern in CSRF_WHITE_LIST:
        if pattern.match(request.url.path):
            return

    csrf_token = _extract_csrf_token(request)
    csrf_token_cookie = _extract_csrf_cookie(request)
    if csrf_token is None or csrf_token != csrf_token_cookie:
        raise unauthorized("unauthorized", "CSRF token is missing or invalid.")

    try:
        verified = PassportService().verify(csrf_token)
    except Exception as exc:
        raise unauthorized("unauthorized", "CSRF token is missing or invalid.") from exc

    subject = verified.get("sub")
    expiry = verified.get("exp")
    if subject != user_id or not isinstance(expiry, int):
        raise unauthorized("unauthorized", "CSRF token is missing or invalid.")

    if expiry < int(datetime.now(UTC).timestamp()):
        raise unauthorized("unauthorized", "CSRF token is missing or invalid.")


async def _get_system_features():
    return await asyncio.to_thread(FeatureService.get_system_features)


async def _require_email_password_login() -> None:
    features = await _get_system_features()
    if not features.enable_email_password_login:
        raise forbidden("forbidden", "Forbidden.")


async def _require_email_register_enabled() -> None:
    features = await _get_system_features()
    if not features.is_allow_register:
        raise forbidden("forbidden", "Forbidden.")


async def _resolve_console_account(request: Request) -> Account:
    token = _extract_access_token(request)
    if not token:
        raise unauthorized("unauthorized", "Unauthorized.")

    try:
        decoded = PassportService().verify(token)
    except Exception as exc:
        raise unauthorized("unauthorized", "Unauthorized.") from exc

    user_id = decoded.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise unauthorized("unauthorized", "Unauthorized.")

    try:
        account = await asyncio.to_thread(AccountService.load_user, user_id)
    except Exception as exc:
        raise unauthorized("unauthorized", "Unauthorized.") from exc

    if account is None or account.current_tenant_id is None:
        raise unauthorized("unauthorized", "Unauthorized.")
    return account


async def _require_console_account(
    request: Request,
    *,
    require_initialized: bool = False,
    require_admin_or_owner: bool = False,
    enforce_csrf: bool = False,
) -> Account:
    account = await _resolve_console_account(request)
    if enforce_csrf:
        _validate_csrf(request, account.id)
    if require_initialized and account.status == AccountStatus.UNINITIALIZED:
        raise _account_not_initialized_error()
    if require_admin_or_owner and not account.is_admin_or_owner:
        raise forbidden("forbidden", "Forbidden.")
    return account


def _decrypt_password(password: str) -> str:
    decoded = FieldEncryption.decrypt_field(password)
    if decoded is None:
        raise _authentication_failed_error("Invalid encrypted data")
    return decoded


def _decrypt_code(code: str) -> str:
    decoded = FieldEncryption.decrypt_field(code)
    if decoded is None:
        raise _email_code_error("Invalid encrypted code")
    return decoded


def _normalize_language(language: str | None) -> str:
    if language == "zh-Hans":
        return "zh-Hans"
    if language is not None and language in languages:
        return language
    return _EN_US


def _preferred_interface_language(request: Request) -> str:
    accept_language = request.headers.get("Accept-Language", "")
    for lang in (item.split(";", 1)[0].strip() for item in accept_language.split(",")):
        if lang in languages:
            return lang
    return languages[0]


def _get_account_with_case_fallback(email: str) -> Account | None:
    return AccountService.get_account_by_email_with_case_fallback(email)


def _authenticate_account_with_case_fallback(
    original_email: str,
    normalized_email: str,
    password: str,
    invite_token: str | None,
) -> Account:
    try:
        return AccountService.authenticate(original_email, password, invite_token)
    except Exception as exc:
        password_error = exc.__class__.__name__ == "AccountPasswordError"
        if not password_error or original_email == normalized_email:
            raise
        return AccountService.authenticate(normalized_email, password, invite_token)


def _log_console_login_failure(*, email: str, reason: LoginFailureReason, request: Request) -> None:
    logger.warning(
        "Console login failed: email=%s reason=%s ip_address=%s",
        email,
        reason,
        _extract_remote_ip(request),
    )


def _get_oauth_providers() -> dict[str, GitHubOAuth | GoogleOAuth | None]:
    github_oauth = (
        None
        if not dify_config.GITHUB_CLIENT_ID or not dify_config.GITHUB_CLIENT_SECRET
        else GitHubOAuth(
            client_id=dify_config.GITHUB_CLIENT_ID,
            client_secret=dify_config.GITHUB_CLIENT_SECRET,
            redirect_uri=dify_config.CONSOLE_API_URL + "/console/api/oauth/authorize/github",
        )
    )
    google_oauth = (
        None
        if not dify_config.GOOGLE_CLIENT_ID or not dify_config.GOOGLE_CLIENT_SECRET
        else GoogleOAuth(
            client_id=dify_config.GOOGLE_CLIENT_ID,
            client_secret=dify_config.GOOGLE_CLIENT_SECRET,
            redirect_uri=dify_config.CONSOLE_API_URL + "/console/api/oauth/authorize/google",
        )
    )
    return {"github": github_oauth, "google": google_oauth}


def _get_account_by_openid_or_email(provider: str, user_info: OAuthUserInfo) -> Account | None:
    account = Account.get_by_openid(provider, user_info.id)
    if account is None:
        account = AccountService.get_account_by_email_with_case_fallback(user_info.email)
    return account


def _generate_oauth_account(provider: str, user_info: OAuthUserInfo, preferred_language: str) -> tuple[Account, bool]:
    account = _get_account_by_openid_or_email(provider, user_info)
    oauth_new_user = False

    if account:
        tenants = TenantService.get_join_tenants(account)
        if not tenants:
            if not FeatureService.get_system_features().is_allow_create_workspace:
                raise WorkSpaceNotAllowedCreateError()
            new_tenant = TenantService.create_tenant(f"{account.name}'s Workspace")
            TenantService.create_tenant_member(new_tenant, account, role="owner")
            account.current_tenant = new_tenant
            tenant_was_created.send(new_tenant)

    if account is None:
        normalized_email = user_info.email.lower()
        oauth_new_user = True
        if not FeatureService.get_system_features().is_allow_register:
            if dify_config.BILLING_ENABLED and BillingService.is_email_in_freeze(normalized_email):
                raise AccountRegisterError(
                    description=(
                        "This email account has been deleted within the past "
                        "30 days and is temporarily unavailable for new account registration"
                    )
                )
            raise AccountRegisterError(description="Invalid email or password")

        account_name = user_info.name or "Dify"
        account = RegisterService.register(
            email=normalized_email,
            name=account_name,
            password=None,
            open_id=user_info.id,
            provider=provider,
        )
        account.interface_language = preferred_language
        with get_sync_session_maker().begin() as session:
            session.merge(account)

    AccountService.link_account_integrate(provider, user_info.id, account)
    return account, oauth_new_user


def _get_notion_oauth_provider() -> NotionOAuth:
    return NotionOAuth(
        client_id=dify_config.NOTION_CLIENT_ID or "",
        client_secret=dify_config.NOTION_CLIENT_SECRET or "",
        redirect_uri=dify_config.CONSOLE_API_URL + "/console/api/oauth/data-source/callback/notion",
    )


def _exchange_notion_access_token(provider: NotionOAuth, code: str) -> tuple[str, str | None, str | None, str | None]:
    headers = {"Accept": "application/json"}
    auth = (provider.client_id, provider.client_secret)
    body = {"code": code, "grant_type": "authorization_code", "redirect_uri": provider.redirect_uri}
    token_response = cast(
        httpx.Response,
        oauth_data_source_lib._http_client.post(
            provider._TOKEN_URL,
            data=body,
            auth=auth,
            headers=headers,
        ),
    )
    token_json = token_response.json()
    access_token = token_json.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError(f"Error in Notion OAuth: {token_json}")
    workspace_name = token_json.get("workspace_name")
    workspace_icon = token_json.get("workspace_icon")
    workspace_id = token_json.get("workspace_id")
    return access_token, cast(str | None, workspace_name), cast(str | None, workspace_icon), cast(str | None, workspace_id)


async def _upsert_notion_binding(
    *,
    tenant_id: str,
    access_token: str,
    workspace_name: str | None,
    workspace_icon: str | None,
    workspace_id: str | None,
    provider: NotionOAuth,
) -> None:
    pages = await asyncio.to_thread(provider.get_authorized_pages, access_token)
    source_info = provider._build_source_info(
        workspace_name=workspace_name,
        workspace_icon=workspace_icon,
        workspace_id=workspace_id,
        pages=pages,
    )

    async with db.session_context() as session:
        existing = await session.scalar(
            select(DataSourceOauthBinding).where(
                DataSourceOauthBinding.tenant_id == tenant_id,
                DataSourceOauthBinding.provider == "notion",
                DataSourceOauthBinding.access_token == access_token,
            )
        )
        payload = SOURCE_INFO_STORAGE_ADAPTER.validate_python(source_info)
        if existing is not None:
            existing.source_info = payload
            existing.disabled = False
            existing.updated_at = naive_utc_now()
        else:
            session.add(
                DataSourceOauthBinding(
                    tenant_id=tenant_id,
                    access_token=access_token,
                    source_info=payload,
                    provider="notion",
                )
            )
        await session.commit()


async def _sync_notion_binding(*, tenant_id: str, binding_id: str, provider: NotionOAuth) -> None:
    async with db.session_context() as session:
        binding = await session.scalar(
            select(DataSourceOauthBinding).where(
                DataSourceOauthBinding.tenant_id == tenant_id,
                DataSourceOauthBinding.provider == "notion",
                DataSourceOauthBinding.id == str(binding_id),
                DataSourceOauthBinding.disabled.is_(False),
            )
        )
        if binding is None:
            raise ValueError("Data source binding not found")
        source_info = NOTION_SOURCE_INFO_ADAPTER.validate_python(binding.source_info)
        access_token = binding.access_token

    pages = await asyncio.to_thread(provider.get_authorized_pages, access_token)
    updated_info = provider._build_source_info(
        workspace_name=source_info["workspace_name"],
        workspace_icon=source_info["workspace_icon"],
        workspace_id=source_info["workspace_id"],
        pages=pages,
    )

    async with db.session_context() as session:
        binding = await session.scalar(
            select(DataSourceOauthBinding).where(
                DataSourceOauthBinding.tenant_id == tenant_id,
                DataSourceOauthBinding.provider == "notion",
                DataSourceOauthBinding.id == str(binding_id),
                DataSourceOauthBinding.disabled.is_(False),
            )
        )
        if binding is None:
            raise ValueError("Data source binding not found")
        binding.source_info = SOURCE_INFO_STORAGE_ADAPTER.validate_python(updated_info)
        binding.disabled = False
        binding.updated_at = naive_utc_now()
        await session.commit()


def _oauth_provider_not_found() -> JSONResponse:
    return JSONResponse(status_code=400, content=ErrorResponse(error="Invalid provider"))


def _oauth_server_error(message: str, *, status_code: int = 400, www_authenticate: bool = False) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=ErrorResponse(error=message))
    if www_authenticate:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


@router.post("/console/api/login")
async def login_console(request: Request, payload: LoginPayload) -> Response:
    await _ensure_console_setup()
    await _require_email_password_login()

    request_email = payload.email
    normalized_email = request_email.lower()
    password = _decrypt_password(payload.password)

    if dify_config.BILLING_ENABLED and await asyncio.to_thread(BillingService.is_email_in_freeze, normalized_email):
        _log_console_login_failure(email=normalized_email, reason=LoginFailureReason.ACCOUNT_IN_FREEZE, request=request)
        raise _account_in_freeze_error()

    if await asyncio.to_thread(AccountService.is_login_error_rate_limit, normalized_email):
        _log_console_login_failure(email=normalized_email, reason=LoginFailureReason.LOGIN_RATE_LIMITED, request=request)
        raise _email_password_login_limit_error()

    invite_token = payload.invite_token
    invitation_data: InvitationDetailDict | None = None
    if invite_token:
        invitation_data = await asyncio.to_thread(
            RegisterService.get_invitation_with_case_fallback,
            None,
            request_email,
            invite_token,
        )
        if invitation_data is None:
            invite_token = None

    try:
        if invitation_data:
            data = invitation_data.get("data", {})
            invitee_email = data.get("email") if data else None
            normalized_invitee = invitee_email.lower() if isinstance(invitee_email, str) else invitee_email
            if normalized_invitee != normalized_email:
                _log_console_login_failure(
                    email=normalized_email,
                    reason=LoginFailureReason.INVALID_INVITATION_EMAIL,
                    request=request,
                )
                raise _invalid_email_error()

        account = await asyncio.to_thread(
            _authenticate_account_with_case_fallback,
            request_email,
            normalized_email,
            password,
            invite_token,
        )
    except ApiError:
        raise
    except Exception as exc:
        exc_name = exc.__class__.__name__
        if exc_name == "AccountLoginError":
            _log_console_login_failure(email=normalized_email, reason=LoginFailureReason.ACCOUNT_BANNED, request=request)
            raise _account_banned_error() from exc
        if exc_name == "AccountPasswordError":
            await asyncio.to_thread(AccountService.add_login_error_rate_limit, normalized_email)
            _log_console_login_failure(email=normalized_email, reason=LoginFailureReason.INVALID_CREDENTIALS, request=request)
            raise _authentication_failed_error() from exc
        raise

    tenants = await asyncio.to_thread(TenantService.get_join_tenants, account)
    if len(tenants) == 0:
        system_features = await _get_system_features()
        if system_features.is_allow_create_workspace and not system_features.license.workspaces.is_available():
            raise _workspaces_limit_exceeded_error()
        return JSONResponse(
            content=ResultFailDataResponse(
                result="fail",
                data="workspace not found, please contact system admin to invite you to join in a workspace",
            )
        )

    token_pair = await asyncio.to_thread(AccountService.login, account, ip_address=_extract_remote_ip(request))
    await asyncio.to_thread(AccountService.reset_login_error_rate_limit, normalized_email)
    response = JSONResponse(content=ResultSuccessResponse(result="success"))
    _set_auth_cookies(response, token_pair)
    return response


@router.post("/console/api/logout")
async def logout_console(request: Request) -> Response:
    await _ensure_console_setup()
    response = JSONResponse(content=ResultSuccessResponse(result="success"))
    token = _extract_access_token(request)
    if token:
        with_context_account = None
        try:
            with_context_account = await _resolve_console_account(request)
        except ApiError:
            with_context_account = None
        if with_context_account is not None:
            await asyncio.to_thread(AccountService.logout, account=with_context_account)
    _clear_auth_cookies(response)
    return response


@router.post("/console/api/reset-password")
async def send_reset_password(request: Request, payload: EmailPayload) -> ResultSuccessWithDataResponse:
    await _ensure_console_setup()
    await _require_email_password_login()

    normalized_email = payload.email.lower()
    if await asyncio.to_thread(AccountService.is_email_send_ip_limit, _extract_remote_ip(request)):
        raise _email_send_ip_limit_error()

    try:
        account = await asyncio.to_thread(_get_account_with_case_fallback, payload.email)
    except AccountRegisterError as exc:
        raise _account_in_freeze_error() from exc

    try:
        token = await asyncio.to_thread(
            AccountService.send_reset_password_email,
            account,
            normalized_email,
            _normalize_language(payload.language),
            (await _get_system_features()).is_allow_register,
        )
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc

    return ResultSuccessWithDataResponse(result="success", data=token)


@router.post("/console/api/email-code-login")
async def send_email_code_login(request: Request, payload: EmailPayload) -> ResultSuccessWithDataResponse:
    await _ensure_console_setup()

    normalized_email = payload.email.lower()
    if await asyncio.to_thread(AccountService.is_email_send_ip_limit, _extract_remote_ip(request)):
        raise _email_send_ip_limit_error()

    try:
        account = await asyncio.to_thread(_get_account_with_case_fallback, payload.email)
    except AccountRegisterError as exc:
        raise _account_in_freeze_error() from exc

    if account is None and not (await _get_system_features()).is_allow_register:
        raise _account_not_found_error()

    try:
        token = await asyncio.to_thread(
            AccountService.send_email_code_login_email,
            account,
            normalized_email if account is None else None,
            _normalize_language(payload.language),
        )
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc
    return ResultSuccessWithDataResponse(result="success", data=token)


@router.post("/console/api/email-code-login/validity")
async def validate_email_code_login(request: Request, payload: EmailCodeLoginPayload) -> Response:
    await _ensure_console_setup()
    code = _decrypt_code(payload.code)
    original_email = payload.email
    user_email = original_email.lower()

    token_data = await asyncio.to_thread(AccountService.get_email_code_login_data, payload.token)
    if token_data is None:
        _log_console_login_failure(email=user_email, reason=LoginFailureReason.INVALID_EMAIL_CODE_TOKEN, request=request)
        raise _invalid_token_error()

    token_email = token_data.get("email")
    normalized_token_email = token_email.lower() if isinstance(token_email, str) else token_email
    if normalized_token_email != user_email:
        _log_console_login_failure(email=user_email, reason=LoginFailureReason.EMAIL_CODE_EMAIL_MISMATCH, request=request)
        raise _invalid_email_error()
    if token_data.get("code") != code:
        _log_console_login_failure(email=user_email, reason=LoginFailureReason.INVALID_EMAIL_CODE, request=request)
        raise _email_code_error()

    await asyncio.to_thread(AccountService.revoke_email_code_login_token, payload.token)

    try:
        account = await asyncio.to_thread(_get_account_with_case_fallback, original_email)
    except Exception as exc:
        exc_name = exc.__class__.__name__
        if exc_name == "Unauthorized":
            _log_console_login_failure(email=user_email, reason=LoginFailureReason.ACCOUNT_BANNED, request=request)
            raise _account_banned_error() from exc
        if isinstance(exc, AccountRegisterError):
            _log_console_login_failure(email=user_email, reason=LoginFailureReason.ACCOUNT_IN_FREEZE, request=request)
            raise _account_in_freeze_error() from exc
        raise

    if account is not None:
        tenants = await asyncio.to_thread(TenantService.get_join_tenants, account)
        if not tenants:
            system_features = await _get_system_features()
            if not system_features.license.workspaces.is_available():
                raise _workspaces_limit_exceeded_error()
            if not system_features.is_allow_create_workspace:
                raise _not_allowed_create_workspace_error()
            new_tenant = await asyncio.to_thread(TenantService.create_tenant, f"{account.name}'s Workspace")
            await asyncio.to_thread(TenantService.create_tenant_member, new_tenant, account, "owner")
            account.current_tenant = new_tenant
            tenant_was_created.send(new_tenant)

    if account is None:
        try:
            account = await asyncio.to_thread(
                AccountService.create_account_and_tenant,
                user_email,
                user_email,
                get_valid_language(payload.language),
                None,
            )
        except WorkSpaceNotAllowedCreateError as exc:
            raise _not_allowed_create_workspace_error() from exc
        except AccountRegisterError as exc:
            _log_console_login_failure(email=user_email, reason=LoginFailureReason.ACCOUNT_IN_FREEZE, request=request)
            raise _account_in_freeze_error() from exc
        except Exception as exc:
            if exc.__class__.__name__ == "WorkspacesLimitExceededError":
                raise _workspaces_limit_exceeded_error() from exc
            raise

    token_pair = await asyncio.to_thread(AccountService.login, account, ip_address=_extract_remote_ip(request))
    await asyncio.to_thread(AccountService.reset_login_error_rate_limit, user_email)
    response = JSONResponse(content=ResultSuccessResponse(result="success"))
    _set_auth_cookies(response, token_pair)
    return response


@router.post("/console/api/refresh-token")
async def refresh_console_token(request: Request) -> Response:
    refresh_token = _extract_refresh_token(request)
    if not refresh_token:
        return JSONResponse(
            status_code=401,
            content=ResultFailMessageResponse(result="fail", message="No refresh token provided"),
        )
    try:
        token_pair = await asyncio.to_thread(AccountService.refresh_token, refresh_token)
    except Exception as exc:
        return JSONResponse(
            status_code=401,
            content=ResultFailMessageResponse(result="fail", message=str(exc)),
        )

    response = JSONResponse(content=ResultSuccessResponse(result="success"))
    _set_auth_cookies(response, token_pair)
    return response


@router.get("/console/api/activate/check")
async def check_activate_token(workspace_id: str | None = None, email: str | None = None, token: str = "") -> ActivationCheckResponse:
    args = ActivateCheckQuery(workspace_id=workspace_id, email=email, token=token)
    invitation = await asyncio.to_thread(
        RegisterService.get_invitation_with_case_fallback,
        args.workspace_id,
        args.email,
        args.token,
    )
    if invitation is None:
        return ActivationCheckResponse(is_valid=False)

    data = invitation.get("data", {})
    tenant = invitation.get("tenant")
    workspace_name = getattr(tenant, "name", None)
    workspace_id_value = str(getattr(tenant, "id", None)) if getattr(tenant, "id", None) is not None else None
    invitee_email = data.get("email") if data else None
    return ActivationCheckResponse(
        is_valid=True,
        data=ActivationCheckData(
            workspace_name=workspace_name,
            workspace_id=workspace_id_value,
            email=cast(str | None, invitee_email),
        ),
    )


def _activate_account_from_invitation(payload: ActivatePayload) -> ResultSuccessResponse:
    normalized_request_email = payload.email.lower() if payload.email else None
    invitation = RegisterService.get_invitation_with_case_fallback(payload.workspace_id, payload.email, payload.token)
    if invitation is None:
        raise _already_activate_error()

    RegisterService.revoke_token(payload.workspace_id, normalized_request_email, payload.token)
    with get_sync_session_maker().begin() as session:
        account = session.merge(invitation["account"])
        if not isinstance(account, Account):
            raise _already_activate_error()
        account.name = payload.name
        account.interface_language = payload.interface_language
        account.timezone = payload.timezone
        account.interface_theme = "light"
        account.status = AccountStatus.ACTIVE
        account.initialized_at = naive_utc_now()
    return ResultSuccessResponse(result="success")


@router.post("/console/api/activate")
async def activate_account(payload: ActivatePayload) -> ResultSuccessResponse:
    try:
        return await asyncio.to_thread(_activate_account_from_invitation, payload)
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc


@router.post("/console/api/forgot-password")
async def forgot_password(request: Request, payload: ForgotPasswordSendPayload) -> ResultSuccessWithDataResponse:
    await _ensure_console_setup()
    await _require_email_password_login()

    if await asyncio.to_thread(AccountService.is_email_send_ip_limit, _extract_remote_ip(request)):
        raise _email_send_ip_limit_error()

    account = await asyncio.to_thread(AccountService.get_account_by_email_with_case_fallback, payload.email)
    try:
        token = await asyncio.to_thread(
            AccountService.send_reset_password_email,
            account,
            payload.email.lower(),
            _normalize_language(payload.language),
            (await _get_system_features()).is_allow_register,
        )
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc
    return ResultSuccessWithDataResponse(result="success", data=token)


@router.post("/console/api/forgot-password/validity")
async def forgot_password_validity(payload: ForgotPasswordCheckPayload) -> ValidityResponse:
    await _ensure_console_setup()
    await _require_email_password_login()

    user_email = payload.email.lower()
    if await asyncio.to_thread(AccountService.is_forgot_password_error_rate_limit, user_email):
        raise _email_password_reset_limit_error()

    token_data = await asyncio.to_thread(AccountService.get_reset_password_data, payload.token)
    if token_data is None:
        raise _invalid_token_error()
    token_email = token_data.get("email")
    if not isinstance(token_email, str) or user_email != token_email.lower():
        raise _invalid_email_error()
    if payload.code != token_data.get("code"):
        await asyncio.to_thread(AccountService.add_forgot_password_error_rate_limit, user_email)
        raise _email_code_error()

    await asyncio.to_thread(AccountService.revoke_reset_password_token, payload.token)
    _, new_token = await asyncio.to_thread(
        AccountService.generate_reset_password_token,
        token_email,
        None,
        payload.code,
        {"phase": "reset"},
    )
    await asyncio.to_thread(AccountService.reset_forgot_password_error_rate_limit, user_email)
    return ValidityResponse(is_valid=True, email=token_email.lower(), token=new_token)


def _reset_password(payload: ForgotPasswordResetPayload) -> ResultSuccessResponse:
    if payload.new_password != payload.password_confirm:
        raise _password_mismatch_error()

    reset_data = AccountService.get_reset_password_data(payload.token)
    if not reset_data or reset_data.get("phase", "") != "reset":
        raise _invalid_token_error()

    AccountService.revoke_reset_password_token(payload.token)
    salt = secrets.token_bytes(16)
    password_hashed = hash_password(payload.new_password, salt)
    email = cast(str, reset_data.get("email", ""))
    account = AccountService.get_account_by_email_with_case_fallback(email)
    if account is None:
        raise _account_not_found_error()

    with get_sync_session_maker().begin() as session:
        account = session.merge(account)
        if not isinstance(account, Account):
            raise _account_not_found_error()
        account.password = base64.b64encode(password_hashed).decode()
        account.password_salt = base64.b64encode(salt).decode()
        if not TenantService.get_join_tenants(account) and FeatureService.get_system_features().is_allow_create_workspace:
            tenant = TenantService.create_tenant(f"{account.name}'s Workspace")
            TenantService.create_tenant_member(tenant, account, role="owner")
            account.current_tenant = tenant
            tenant_was_created.send(tenant)
    return ResultSuccessResponse(result="success")


@router.post("/console/api/forgot-password/resets")
async def forgot_password_reset(payload: ForgotPasswordResetPayload) -> ResultSuccessResponse:
    await _ensure_console_setup()
    await _require_email_password_login()
    try:
        return await asyncio.to_thread(_reset_password, payload)
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc


@router.post("/console/api/email-register/send-email")
async def email_register_send(request: Request, payload: EmailRegisterSendPayload) -> ResultSuccessWithDataResponse:
    await _ensure_console_setup()
    await _require_email_password_login()
    await _require_email_register_enabled()

    normalized_email = payload.email.lower()
    if await asyncio.to_thread(AccountService.is_email_send_ip_limit, _extract_remote_ip(request)):
        raise _email_send_ip_limit_error()
    if dify_config.BILLING_ENABLED and await asyncio.to_thread(BillingService.is_email_in_freeze, normalized_email):
        raise _account_in_freeze_error()

    account = await asyncio.to_thread(AccountService.get_account_by_email_with_case_fallback, payload.email)
    try:
        token = await asyncio.to_thread(
            AccountService.send_email_register_email,
            account,
            normalized_email,
            _normalize_language(payload.language),
        )
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc
    return ResultSuccessWithDataResponse(result="success", data=token)


@router.post("/console/api/email-register/validity")
async def email_register_validity(payload: EmailRegisterValidityPayload) -> ValidityResponse:
    await _ensure_console_setup()
    await _require_email_password_login()
    await _require_email_register_enabled()

    user_email = payload.email.lower()
    if await asyncio.to_thread(AccountService.is_email_register_error_rate_limit, user_email):
        raise _email_register_limit_error()

    token_data = await asyncio.to_thread(AccountService.get_email_register_data, payload.token)
    if token_data is None:
        raise _invalid_token_error()
    token_email = token_data.get("email")
    normalized_token_email = token_email.lower() if isinstance(token_email, str) else token_email
    if normalized_token_email != user_email:
        raise _invalid_email_error()
    if payload.code != token_data.get("code"):
        await asyncio.to_thread(AccountService.add_email_register_error_rate_limit, user_email)
        raise _email_code_error()

    await asyncio.to_thread(AccountService.revoke_email_register_token, payload.token)
    _, new_token = await asyncio.to_thread(
        AccountService.generate_email_register_token,
        user_email,
        payload.code,
        {"phase": "register"},
    )
    await asyncio.to_thread(AccountService.reset_email_register_error_rate_limit, user_email)
    return ValidityResponse(is_valid=True, email=user_email, token=new_token)


def _create_email_register_account(payload: EmailRegisterResetPayload, request: Request) -> ResultSuccessWithTokenDataResponse:
    if payload.new_password != payload.password_confirm:
        raise _password_mismatch_error()
    register_data = AccountService.get_email_register_data(payload.token)
    if not register_data or register_data.get("phase", "") != "register":
        raise _invalid_token_error()

    AccountService.revoke_email_register_token(payload.token)
    email = cast(str, register_data.get("email", ""))
    normalized_email = email.lower()
    account = AccountService.get_account_by_email_with_case_fallback(email)
    if account is not None:
        raise _email_already_in_use_error()

    try:
        created = AccountService.create_account_and_tenant(
            email=normalized_email,
            name=email,
            password=payload.password_confirm,
            interface_language=languages[0],
        )
    except AccountRegisterError as exc:
        raise _account_in_freeze_error() from exc

    token_pair = AccountService.login(created, ip_address=_extract_remote_ip(request))
    AccountService.reset_login_error_rate_limit(normalized_email)
    return ResultSuccessWithTokenDataResponse(result="success", data=token_pair.model_dump())


@router.post("/console/api/email-register")
async def email_register(request: Request, payload: EmailRegisterResetPayload) -> ResultSuccessWithTokenDataResponse:
    await _ensure_console_setup()
    await _require_email_password_login()
    await _require_email_register_enabled()
    try:
        return await asyncio.to_thread(_create_email_register_account, payload, request)
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc


@router.get("/console/api/oauth/login/{provider}")
async def oauth_login(provider: str, invite_token: str | None = None) -> Response:
    oauth_provider = _get_oauth_providers().get(provider)
    if oauth_provider is None:
        return _oauth_provider_not_found()
    auth_url = await asyncio.to_thread(oauth_provider.get_authorization_url, invite_token)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/console/api/oauth/authorize/{provider}")
async def oauth_authorize(request: Request, provider: str, code: str | None = None, state: str | None = None) -> Response:
    oauth_provider = _get_oauth_providers().get(provider)
    if oauth_provider is None:
        return _oauth_provider_not_found()
    if not code:
        return JSONResponse(status_code=400, content=ErrorResponse(error="Authorization code is required"))

    invite_token = state or None
    try:
        token = await asyncio.to_thread(oauth_provider.get_access_token, code)
        user_info = await asyncio.to_thread(oauth_provider.get_user_info, token)
    except httpx.RequestError as exc:
        logger.exception("OAuth process failed for %s: %s", provider, str(exc))
        return JSONResponse(status_code=400, content=ErrorResponse(error="OAuth process failed"))
    except ValueError as exc:
        return RedirectResponse(
            url=f"{dify_config.CONSOLE_WEB_URL}/signin?message={urllib.parse.quote(str(exc))}",
            status_code=302,
        )

    if invite_token and await asyncio.to_thread(RegisterService.is_valid_invite_token, invite_token):
        invitation = await asyncio.to_thread(RegisterService.get_invitation_by_token, invite_token)
        if invitation:
            invitation_email = invitation.get("email")
            normalized_invitation = invitation_email.lower() if isinstance(invitation_email, str) else invitation_email
            if normalized_invitation != user_info.email.lower():
                return RedirectResponse(
                    url=f"{dify_config.CONSOLE_WEB_URL}/signin?message=Invalid invitation token.",
                    status_code=302,
                )
        return RedirectResponse(
            url=f"{dify_config.CONSOLE_WEB_URL}/signin/invite-settings?invite_token={invite_token}",
            status_code=302,
        )

    try:
        account, oauth_new_user = await asyncio.to_thread(
            _generate_oauth_account,
            provider,
            user_info,
            _preferred_interface_language(request),
        )
    except AccountRegisterError as exc:
        return RedirectResponse(
            url=f"{dify_config.CONSOLE_WEB_URL}/signin?message={urllib.parse.quote(str(exc.description or ''))}",
            status_code=302,
        )
    except WorkSpaceNotFoundError:
        return RedirectResponse(
            url=(
                f"{dify_config.CONSOLE_WEB_URL}/signin"
                "?message=Workspace not found, please contact system admin to invite you to join in a workspace."
            ),
            status_code=302,
        )
    except WorkSpaceNotAllowedCreateError:
        return RedirectResponse(
            url=(
                f"{dify_config.CONSOLE_WEB_URL}/signin"
                "?message=Workspace not found, please contact system admin to invite you to join in a workspace."
            ),
            status_code=302,
        )

    if account.status == AccountStatus.BANNED:
        return RedirectResponse(url=f"{dify_config.CONSOLE_WEB_URL}/signin?message=Account is banned.", status_code=302)
    if account.status == AccountStatus.PENDING:
        def _activate_pending_account() -> None:
            with get_sync_session_maker().begin() as session:
                pending_account = session.merge(account)
                if isinstance(pending_account, Account):
                    pending_account.status = AccountStatus.ACTIVE
                    pending_account.initialized_at = naive_utc_now()

        await asyncio.to_thread(_activate_pending_account)

    try:
        await asyncio.to_thread(TenantService.create_owner_tenant_if_not_exist, account)
    except Exception as exc:
        if exc.__class__.__name__ == "Unauthorized":
            return RedirectResponse(
                url=f"{dify_config.CONSOLE_WEB_URL}/signin?message=Workspace not found.",
                status_code=302,
            )
        if isinstance(exc, WorkSpaceNotAllowedCreateError):
            return RedirectResponse(
                url=(
                    f"{dify_config.CONSOLE_WEB_URL}/signin"
                    "?message=Workspace not found, please contact system admin to invite you to join in a workspace."
                ),
                status_code=302,
            )
        raise

    token_pair = await asyncio.to_thread(AccountService.login, account, ip_address=_extract_remote_ip(request))
    base_url = dify_config.CONSOLE_WEB_URL
    query_char = "&" if "?" in base_url else "?"
    target_url = f"{base_url}{query_char}oauth_new_user={str(oauth_new_user).lower()}"
    response = RedirectResponse(url=target_url, status_code=302)
    _set_auth_cookies(response, token_pair)
    return response


@router.post("/console/api/oauth/provider", response_model=None)
async def oauth_provider_info(payload: OAuthProviderRequest) -> OAuthProviderInfoResponse | JSONResponse:
    await _ensure_console_setup()
    oauth_provider_app = await asyncio.to_thread(OAuthServerService.get_oauth_provider_app, payload.client_id)
    if oauth_provider_app is None:
        return _oauth_server_error("client_id is invalid", status_code=404)
    if payload.redirect_uri not in oauth_provider_app.redirect_uris:
        return _oauth_server_error("redirect_uri is invalid")
    return OAuthProviderInfoResponse(
        app_icon=oauth_provider_app.app_icon,
        app_label=str(oauth_provider_app.app_label),
        scope=oauth_provider_app.scope,
    )


@router.post("/console/api/oauth/provider/authorize", response_model=None)
async def oauth_provider_authorize(request: Request, payload: OAuthClientPayload) -> OAuthAuthorizeCodeResponse | JSONResponse:
    await _ensure_console_setup()
    account = await _require_console_account(request, require_initialized=True, enforce_csrf=True)
    oauth_provider_app = await asyncio.to_thread(OAuthServerService.get_oauth_provider_app, payload.client_id)
    if oauth_provider_app is None:
        return _oauth_server_error("client_id is invalid", status_code=404)
    code = await asyncio.to_thread(OAuthServerService.sign_oauth_authorization_code, oauth_provider_app.client_id, account.id)
    return OAuthAuthorizeCodeResponse(code=code)


@router.post("/console/api/oauth/provider/token", response_model=None)
async def oauth_provider_token(payload: OAuthTokenRequest) -> OAuthTokenResponse | JSONResponse:
    await _ensure_console_setup()
    oauth_provider_app = await asyncio.to_thread(OAuthServerService.get_oauth_provider_app, payload.client_id)
    if oauth_provider_app is None:
        return _oauth_server_error("client_id is invalid", status_code=404)

    try:
        grant_type = OAuthGrantType(payload.grant_type)
    except ValueError:
        return _oauth_server_error("invalid grant_type")

    if grant_type == OAuthGrantType.AUTHORIZATION_CODE:
        if not payload.code:
            return _oauth_server_error("code is required")
        if payload.client_secret != oauth_provider_app.client_secret:
            return _oauth_server_error("client_secret is invalid")
        if payload.redirect_uri not in oauth_provider_app.redirect_uris:
            return _oauth_server_error("redirect_uri is invalid")
        try:
            access_token, refresh_token = await asyncio.to_thread(
                OAuthServerService.sign_oauth_access_token,
                grant_type,
                payload.code,
                oauth_provider_app.client_id,
                "",
            )
        except Exception as exc:
            return _oauth_server_error(str(exc))
    else:
        if not payload.refresh_token:
            return _oauth_server_error("refresh_token is required")
        try:
            access_token, refresh_token = await asyncio.to_thread(
                OAuthServerService.sign_oauth_access_token,
                grant_type,
                "",
                oauth_provider_app.client_id,
                payload.refresh_token,
            )
        except Exception as exc:
            return _oauth_server_error(str(exc))

    return OAuthTokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=OAUTH_ACCESS_TOKEN_EXPIRES_IN,
        refresh_token=refresh_token,
    )


@router.post("/console/api/oauth/provider/account", response_model=None)
async def oauth_provider_account(request: Request, payload: OAuthClientPayload) -> OAuthAccountResponse | JSONResponse:
    await _ensure_console_setup()
    oauth_provider_app = await asyncio.to_thread(OAuthServerService.get_oauth_provider_app, payload.client_id)
    if oauth_provider_app is None:
        return _oauth_server_error("client_id is invalid", status_code=404)

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return _oauth_server_error("Authorization header is required", status_code=401, www_authenticate=True)
    parts = auth_header.strip().split(None, 1)
    if len(parts) != 2:
        return _oauth_server_error("Invalid Authorization header format", status_code=401, www_authenticate=True)
    if parts[0].strip().lower() != "bearer":
        return _oauth_server_error("token_type is invalid", status_code=401, www_authenticate=True)
    access_token = parts[1].strip()
    if not access_token:
        return _oauth_server_error("access_token is required", status_code=401, www_authenticate=True)

    account = await asyncio.to_thread(OAuthServerService.validate_oauth_access_token, oauth_provider_app.client_id, access_token)
    if account is None:
        return _oauth_server_error("access_token or client_id is invalid", status_code=401, www_authenticate=True)

    return OAuthAccountResponse(
        name=account.name,
        email=account.email,
        avatar=account.avatar,
        interface_language=account.interface_language,
        timezone=account.timezone,
    )


@router.get("/console/api/oauth/data-source/{provider}", response_model=None)
async def oauth_data_source(request: Request, provider: str) -> OAuthDataSourceResponse | JSONResponse:
    await _ensure_console_setup()
    account = await _require_console_account(request, require_initialized=True, require_admin_or_owner=True)
    if provider != "notion":
        return _oauth_provider_not_found()

    notion = _get_notion_oauth_provider()
    if dify_config.NOTION_INTEGRATION_TYPE == "internal":
        internal_secret = dify_config.NOTION_INTERNAL_SECRET
        if not internal_secret:
            return JSONResponse(content=ErrorResponse(error="Internal secret is not set"))
        workspace_name = await asyncio.to_thread(notion.notion_workspace_name, internal_secret)
        await _upsert_notion_binding(
            tenant_id=account.current_tenant_id or "",
            access_token=internal_secret,
            workspace_name=workspace_name,
            workspace_icon=None,
            workspace_id=account.current_tenant_id,
            provider=notion,
        )
        return OAuthDataSourceResponse(data="internal")

    auth_url = await asyncio.to_thread(notion.get_authorization_url)
    return OAuthDataSourceResponse(data=auth_url)


@router.get("/console/api/oauth/data-source/callback/{provider}")
async def oauth_data_source_callback(provider: str, code: str | None = None, error: str | None = None) -> Response:
    if provider != "notion":
        return _oauth_provider_not_found()
    if code is not None:
        return RedirectResponse(url=f"{dify_config.CONSOLE_WEB_URL}?type=notion&code={code}", status_code=302)
    if error is not None:
        return RedirectResponse(url=f"{dify_config.CONSOLE_WEB_URL}?type=notion&error={error}", status_code=302)
    return RedirectResponse(url=f"{dify_config.CONSOLE_WEB_URL}?type=notion&error=Access denied", status_code=302)


@router.get("/console/api/oauth/data-source/binding/{provider}", response_model=None)
async def oauth_data_source_binding(
    request: Request,
    provider: str,
    code: str | None = None,
) -> OAuthSourceBindingResponse | JSONResponse:
    if provider != "notion":
        return _oauth_provider_not_found()
    if not code:
        return JSONResponse(status_code=400, content=ErrorResponse(error="Invalid code"))

    account = await _require_console_account(request, require_initialized=True)
    notion = _get_notion_oauth_provider()
    try:
        access_token, workspace_name, workspace_icon, workspace_id = await asyncio.to_thread(
            _exchange_notion_access_token, notion, code
        )
    except httpx.HTTPStatusError as exc:
        logger.exception("OAuth data source process failed with %s: %s", provider, exc.response.text)
        return JSONResponse(status_code=400, content=ErrorResponse(error="OAuth data source process failed"))

    await _upsert_notion_binding(
        tenant_id=account.current_tenant_id or "",
        access_token=access_token,
        workspace_name=workspace_name,
        workspace_icon=workspace_icon,
        workspace_id=workspace_id,
        provider=notion,
    )
    return OAuthSourceBindingResponse(result="success")


@router.get("/console/api/oauth/data-source/{provider}/{binding_id}/sync", response_model=None)
async def oauth_data_source_sync(request: Request, provider: str, binding_id: UUID) -> OAuthSourceBindingResponse | JSONResponse:
    await _ensure_console_setup()
    account = await _require_console_account(request, require_initialized=True)
    if provider != "notion":
        return _oauth_provider_not_found()

    notion = _get_notion_oauth_provider()
    try:
        await _sync_notion_binding(tenant_id=account.current_tenant_id or "", binding_id=str(binding_id), provider=notion)
    except httpx.HTTPStatusError as exc:
        logger.exception("OAuth data source sync failed with %s: %s", provider, exc.response.text)
        return JSONResponse(status_code=400, content=ErrorResponse(error="OAuth data source process failed"))

    return OAuthSourceBindingResponse(result="success")


@router.get("/console/api/api-key-auth/data-source")
async def list_api_key_data_sources(request: Request) -> ApiKeySourceListResponse:
    await _ensure_console_setup()
    account = await _require_console_account(request, require_initialized=True)
    bindings = await asyncio.to_thread(ApiKeyAuthService.get_provider_auth_list, account.current_tenant_id or "")
    if not bindings:
        return ApiKeySourceListResponse(sources=[])
    return ApiKeySourceListResponse(
        sources=[
            ApiKeySourceItem(
                id=str(binding.id),
                category=binding.category,
                provider=binding.provider,
                disabled=binding.disabled,
                created_at=int(binding.created_at.timestamp()),
                updated_at=int(binding.updated_at.timestamp()),
            )
            for binding in bindings
        ]
    )


@router.post("/console/api/api-key-auth/data-source/binding")
async def bind_api_key_data_source(request: Request, payload: ApiKeyAuthBindingPayload) -> ResultSuccessResponse:
    await _ensure_console_setup()
    account = await _require_console_account(
        request,
        require_initialized=True,
        require_admin_or_owner=True,
        enforce_csrf=True,
    )
    data = payload.model_dump()
    try:
        await asyncio.to_thread(ApiKeyAuthService.validate_api_key_auth_args, data)
        await asyncio.to_thread(ApiKeyAuthService.create_provider_auth, account.current_tenant_id or "", data)
    except BaseHTTPException as exc:
        raise _api_error_from_legacy(exc) from exc
    except Exception as exc:
        raise _api_key_auth_failed_error(str(exc)) from exc
    return ResultSuccessResponse(result="success")


@router.delete("/console/api/api-key-auth/data-source/{binding_id}")
async def delete_api_key_data_source(request: Request, binding_id: UUID) -> Response:
    await _ensure_console_setup()
    account = await _require_console_account(
        request,
        require_initialized=True,
        require_admin_or_owner=True,
        enforce_csrf=True,
    )
    await asyncio.to_thread(ApiKeyAuthService.delete_provider_auth, account.current_tenant_id or "", str(binding_id))
    return Response(status_code=204)
