from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Query, Request
from packaging import version as packaging_version
from pydantic import BaseModel, Field

from api_server.auth import extract_webapp_passport, verify_passport
from api_server.errors import forbidden, unauthorized
from api_server.services.app_lookup import AppLookupService
from api_server.services.bootstrap import BootstrapService
from configs import dify_config
from constants.dsl_version import CURRENT_APP_DSL_VERSION
from services.enterprise.enterprise_service import EnterpriseService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bootstrap"])


class LicenseLimitationModel(BaseModel):
    enabled: bool = False
    size: int = 0
    limit: int = 0


class LicenseModel(BaseModel):
    status: str = "none"
    expired_at: str = ""
    workspaces: LicenseLimitationModel = LicenseLimitationModel()


class BrandingModel(BaseModel):
    enabled: bool = False
    application_title: str = ""
    login_page_logo: str = ""
    workspace_logo: str = ""
    favicon: str = ""


class WebAppAuthSsoModel(BaseModel):
    protocol: str = ""


class WebAppAuthModel(BaseModel):
    enabled: bool = False
    allow_sso: bool = False
    sso_config: WebAppAuthSsoModel = WebAppAuthSsoModel()
    allow_email_code_login: bool = False
    allow_email_password_login: bool = False


class PluginInstallationPermissionModel(BaseModel):
    plugin_installation_scope: str = "all"
    restrict_to_marketplace_only: bool = False


class PluginManagerModel(BaseModel):
    enabled: bool = False


class SystemFeatureModel(BaseModel):
    app_dsl_version: str
    sso_enforced_for_signin: bool = False
    sso_enforced_for_signin_protocol: str = ""
    enable_marketplace: bool = False
    max_plugin_package_size: int
    enable_email_code_login: bool = False
    enable_email_password_login: bool = True
    enable_social_oauth_login: bool = False
    enable_collaboration_mode: bool = False
    is_allow_register: bool = False
    is_allow_create_workspace: bool = False
    is_email_setup: bool = False
    license: LicenseModel = LicenseModel()
    branding: BrandingModel = BrandingModel()
    webapp_auth: WebAppAuthModel = WebAppAuthModel()
    plugin_installation_permission: PluginInstallationPermissionModel = PluginInstallationPermissionModel()
    enable_change_email: bool = True
    plugin_manager: PluginManagerModel = PluginManagerModel()
    trial_models: list[str] = []
    enable_trial_app: bool = False
    enable_explore_banner: bool = False


class PingResponse(BaseModel):
    result: str = Field(description="Health check result")


class VersionFeatures(BaseModel):
    can_replace_logo: bool = False
    model_load_balancing_enabled: bool = False


class VersionResponse(BaseModel):
    version: str
    release_date: str = ""
    release_notes: str = ""
    can_auto_update: bool = False
    features: VersionFeatures


class SetupStatusResponse(BaseModel):
    step: Literal["not_started", "finished"]
    setup_at: str | None = None


class InitValidatePayload(BaseModel):
    password: str = Field(..., max_length=30, description="Initialization password")


class InitStatusResponse(BaseModel):
    status: Literal["finished", "not_started"] = Field(..., description="Initialization status")


class InitValidateResponse(BaseModel):
    result: str = Field(description="Operation result", examples=["success"])


class SetupRequestPayload(BaseModel):
    email: str = Field(..., description="Admin email address")
    name: str = Field(..., max_length=30, description="Admin name")
    password: str = Field(..., description="Admin password")
    language: str | None = Field(default=None, description="Admin language")


class SetupResponse(BaseModel):
    result: str = Field(description="Setup result", examples=["success"])


class AppAccessModeResponse(BaseModel):
    access_mode: str = Field(alias="accessMode", description="Resolved webapp access mode")


class AppPermissionResponse(BaseModel):
    result: bool = Field(description="Whether the user can access the webapp")


@router.get("/console/api/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    return PingResponse(result="pong")


@router.get("/console/api/version", response_model=VersionResponse)
async def check_version_update(
    current_version: str = Query(..., description="Current application version"),
) -> VersionResponse:
    result = VersionResponse(
        version=dify_config.project.version,
        features=VersionFeatures(
            can_replace_logo=getattr(dify_config, "CAN_REPLACE_LOGO", False),
            model_load_balancing_enabled=getattr(dify_config, "MODEL_LB_ENABLED", False),
        ),
    )

    check_update_url = getattr(dify_config, "CHECK_UPDATE_URL", "")
    if not check_update_url:
        return result

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=10.0, connect=3.0)) as client:
            response = await client.get(check_update_url, params={"current_version": current_version})
        content = response.json()
    except Exception:
        logger.warning("Version check failed", exc_info=True)
        result.version = current_version
        return result

    latest_version = content.get("version", result.version)
    if _has_new_version(latest_version=latest_version, current_version=current_version):
        result.version = latest_version
        result.release_date = content.get("releaseDate", "")
        result.release_notes = content.get("releaseNotes", "")
        result.can_auto_update = content.get("canAutoUpdate", False)

    return result


@router.get("/console/api/setup", response_model=SetupStatusResponse)
async def get_setup_status() -> SetupStatusResponse:
    status = await BootstrapService.get_setup_status()
    return SetupStatusResponse(step=status.step, setup_at=status.setup_at)


@router.post("/console/api/setup", response_model=SetupResponse, status_code=201)
async def setup_system(payload: SetupRequestPayload, request: Request) -> SetupResponse:
    if dify_config.EDITION != "SELF_HOSTED":
        raise forbidden(
            "already_setup",
            "Dify has been successfully installed. Please refresh the page or return to the dashboard homepage.",
        )

    if not await BootstrapService.get_init_validate_status(bool(request.session.get("is_init_validated"))):
        raise unauthorized(
            "not_init_validated",
            "Init validation has not been completed yet. Please proceed with the init validation process first.",
        )

    await BootstrapService.setup(
        email=payload.email,
        name=payload.name,
        password=payload.password,
        language=payload.language,
        ip_address=request.client.host if request.client else "",
    )
    return SetupResponse(result="success")


@router.get("/console/api/init", response_model=InitStatusResponse)
async def get_init_status(request: Request) -> InitStatusResponse:
    init_status = await BootstrapService.get_init_validate_status(bool(request.session.get("is_init_validated")))
    if init_status:
        return InitStatusResponse(status="finished")
    return InitStatusResponse(status="not_started")


@router.post("/console/api/init", response_model=InitValidateResponse, status_code=201)
async def validate_init_password(payload: InitValidatePayload, request: Request) -> InitValidateResponse:
    if await BootstrapService.get_tenant_count() > 0:
        raise forbidden(
            "already_setup",
            "Dify has been successfully installed. Please refresh the page or return to the dashboard homepage.",
        )

    BootstrapService.validate_init_password(payload.password, BootstrapService._get_init_password())
    request.session["is_init_validated"] = True
    return InitValidateResponse(result="success")


@router.get("/console/api/system-features", response_model=SystemFeatureModel)
@router.get("/api/system-features", response_model=SystemFeatureModel)
async def get_system_features() -> SystemFeatureModel:
    email_type = getattr(dify_config, "MAIL_TYPE", None)
    enterprise_enabled = bool(getattr(dify_config, "ENTERPRISE_ENABLED", False))

    return SystemFeatureModel(
        app_dsl_version=CURRENT_APP_DSL_VERSION,
        enable_marketplace=bool(getattr(dify_config, "MARKETPLACE_ENABLED", False)),
        max_plugin_package_size=getattr(dify_config, "PLUGIN_MAX_PACKAGE_SIZE", 15 * 1024 * 1024),
        enable_email_code_login=bool(getattr(dify_config, "ENABLE_EMAIL_CODE_LOGIN", False)),
        enable_email_password_login=bool(getattr(dify_config, "ENABLE_EMAIL_PASSWORD_LOGIN", True)),
        enable_social_oauth_login=bool(getattr(dify_config, "ENABLE_SOCIAL_OAUTH_LOGIN", False)),
        enable_collaboration_mode=bool(getattr(dify_config, "ENABLE_COLLABORATION_MODE", False)),
        is_allow_register=bool(getattr(dify_config, "ALLOW_REGISTER", False)),
        is_allow_create_workspace=bool(getattr(dify_config, "ALLOW_CREATE_WORKSPACE", False)),
        is_email_setup=bool(email_type),
        branding=BrandingModel(enabled=enterprise_enabled),
        webapp_auth=WebAppAuthModel(
            enabled=enterprise_enabled,
            allow_email_code_login=bool(getattr(dify_config, "ENABLE_EMAIL_CODE_LOGIN", False)),
            allow_email_password_login=bool(getattr(dify_config, "ENABLE_EMAIL_PASSWORD_LOGIN", True)),
        ),
        plugin_manager=PluginManagerModel(enabled=enterprise_enabled),
        trial_models=[],
        enable_trial_app=bool(getattr(dify_config, "ENABLE_TRIAL_APP", False)),
        enable_explore_banner=bool(getattr(dify_config, "ENABLE_EXPLORE_BANNER", False)),
    )


@router.get("/api/webapp/access-mode", response_model=AppAccessModeResponse)
async def get_webapp_access_mode(
    app_id: str | None = Query(default=None, alias="appId", description="Application ID"),
    app_code: str | None = Query(default=None, alias="appCode", description="Application code"),
) -> AppAccessModeResponse:
    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        return AppAccessModeResponse(accessMode="public")

    resolved_app_id = app_id
    if app_code:
        resolved_app_id = await AppLookupService.get_app_id_by_code(app_code)

    if not resolved_app_id:
        return AppAccessModeResponse(accessMode="public")

    access_mode = EnterpriseService.WebAppAuth.get_app_access_mode_by_id(resolved_app_id)
    return AppAccessModeResponse(accessMode=access_mode.access_mode)


@router.get("/api/webapp/permission", response_model=AppPermissionResponse)
async def get_webapp_permission(
    request: Request,
    app_id: str | None = Query(default=None, alias="appId", description="Application ID"),
) -> AppPermissionResponse:
    app_code = request.headers.get("X-App-Code")
    if not app_id or not app_code:
        raise unauthorized("missing_webapp_identity", "appId and X-App-Code are required.")

    if not bool(getattr(dify_config, "ENTERPRISE_ENABLED", False)):
        return AppPermissionResponse(result=True)

    access_mode = EnterpriseService.WebAppAuth.get_app_access_mode_by_id(app_id)
    if access_mode.access_mode not in {"private", "private_all"}:
        return AppPermissionResponse(result=True)

    passport = await extract_webapp_passport(app_code, request)
    if not passport:
        raise unauthorized("missing_passport", "Access token is missing.")

    try:
        decoded = verify_passport(passport)
    except Exception:
        logger.exception("Unexpected error during auth verification")
        raise unauthorized("invalid_passport", "Invalid token.")

    user_id = str(decoded.get("user_id", "visitor"))
    result = EnterpriseService.WebAppAuth.is_user_allowed_to_access_webapp(user_id, app_id)
    return AppPermissionResponse(result=result)


def _has_new_version(*, latest_version: str, current_version: str) -> bool:
    try:
        return packaging_version.parse(latest_version) > packaging_version.parse(current_version)
    except packaging_version.InvalidVersion:
        logger.warning("Invalid version format: latest=%s current=%s", latest_version, current_version)
        return False
