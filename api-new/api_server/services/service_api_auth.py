"""FastAPI-native app-token authentication for `/v1` service API routes.

The first service API routes being ported only need app-token scoped access.
Keeping this lookup local avoids Flask decorators, Flask-Login state, and the
broader legacy token-cache stack while preserving the tenant/app invariants that
guard service API requests.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from api_server.errors import forbidden, unauthorized
from api_server.models.app import ApiToken, ApiTokenType, App, AppStatus, Tenant, TenantStatus
from extensions.ext_database import db
from libs.datetime_utils import naive_utc_now

_service_api_bearer = HTTPBearer(auto_error=False)


def _extract_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


@dataclass(slots=True)
class ServiceApiAppContext:
    api_token: ApiToken
    app: App
    tenant: Tenant


class ServiceApiAuthService:
    """Resolve the authenticated app and tenant for a service API request."""

    @staticmethod
    async def extract_app_token(request: Request) -> str:
        token = _extract_bearer_token(await _service_api_bearer(request))
        if not token:
            raise unauthorized(
                "authorization_required",
                "Authorization header must be provided and start with 'Bearer'.",
            )
        return token

    @classmethod
    async def resolve_app_context(cls, request: Request) -> ServiceApiAppContext:
        token = await cls.extract_app_token(request)

        async with db.session_context() as session:
            api_token = await session.scalar(
                select(ApiToken).where(
                    ApiToken.token == token,
                    ApiToken.type == ApiTokenType.APP,
                )
            )
            if api_token is None or api_token.app_id is None:
                raise unauthorized("invalid_api_token", "API key is invalid.")

            app = await session.scalar(select(App).where(App.id == api_token.app_id).limit(1))
            if app is None:
                raise forbidden("app_unavailable", "The app no longer exists.")
            if app.status != AppStatus.NORMAL:
                raise forbidden("app_unavailable", "The app's status is abnormal.")
            if not app.enable_api:
                raise forbidden("api_disabled", "The app's API service has been disabled.")

            tenant = await session.scalar(select(Tenant).where(Tenant.id == app.tenant_id).limit(1))
            if tenant is None:
                raise forbidden("workspace_not_found", "Workspace not found.")
            if tenant.status == TenantStatus.ARCHIVE:
                raise forbidden("workspace_archived", "The workspace's status is archived.")

            api_token.last_used_at = naive_utc_now()
            session.add(api_token)
            await session.flush()

        return ServiceApiAppContext(api_token=api_token, app=app, tenant=tenant)
