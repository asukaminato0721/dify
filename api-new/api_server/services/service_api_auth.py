"""FastAPI-native app-token authentication for `/v1` service API routes.

The first service API routes being ported only need app-token scoped access.
Keeping this lookup local avoids Flask decorators, Flask-Login state, and the
broader legacy token-cache stack while preserving the tenant/app invariants that
guard service API requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from api_server.errors import forbidden, unauthorized
from api_server.models.app import (
    Account,
    ApiToken,
    ApiTokenType,
    App,
    AppStatus,
    DefaultEndUserSessionID,
    EndUser,
    Tenant,
    TenantAccountJoin,
    TenantAccountRole,
    TenantStatus,
)
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


@dataclass(slots=True)
class ServiceApiDatasetContext:
    api_token: ApiToken
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

    @classmethod
    async def resolve_dataset_context(cls, request: Request) -> ServiceApiDatasetContext:
        token = await cls.extract_app_token(request)

        async with db.session_context() as session:
            api_token = await session.scalar(
                select(ApiToken).where(
                    ApiToken.token == token,
                    ApiToken.type == ApiTokenType.DATASET,
                )
            )
            if api_token is None or api_token.tenant_id is None:
                raise unauthorized("invalid_api_token", "API key is invalid.")

            tenant = await session.scalar(select(Tenant).where(Tenant.id == api_token.tenant_id).limit(1))
            if tenant is None:
                raise forbidden("workspace_not_found", "Workspace not found.")
            if tenant.status == TenantStatus.ARCHIVE:
                raise forbidden("workspace_archived", "The workspace's status is archived.")

            api_token.last_used_at = naive_utc_now()
            session.add(api_token)
            await session.flush()

        return ServiceApiDatasetContext(api_token=api_token, tenant=tenant)

    @staticmethod
    async def resolve_end_user(*, app: App, user_id: str | None) -> EndUser:
        session_id = user_id or DefaultEndUserSessionID.DEFAULT_SESSION_ID

        async with db.session_context() as session:
            end_user = await session.scalar(
                select(EndUser).where(
                    EndUser.tenant_id == app.tenant_id,
                    EndUser.app_id == app.id,
                    EndUser.session_id == session_id,
                )
            )
            if end_user is not None:
                if end_user.type != "service-api":
                    end_user.type = "service-api"
                    session.add(end_user)
                    await session.flush()
                return end_user

            end_user = EndUser(
                id=str(uuid4()),
                tenant_id=app.tenant_id,
                app_id=app.id,
                type="service-api",
                external_user_id=session_id,
                name=None,
                is_anonymous=session_id == DefaultEndUserSessionID.DEFAULT_SESSION_ID,
                session_id=session_id,
            )
            session.add(end_user)
            await session.flush()
            await session.refresh(end_user)
            return end_user

    @staticmethod
    async def resolve_owner_account(*, tenant_id: str) -> Account:
        async with db.session_context() as session:
            row = await session.execute(
                select(Account)
                .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
                .where(
                    TenantAccountJoin.tenant_id == tenant_id,
                    TenantAccountJoin.role == TenantAccountRole.OWNER,
                )
                .limit(1)
            )
            account = row.scalar_one_or_none()
        if account is None:
            raise forbidden("owner_not_found", "Tenant owner account not found.")
        return account
