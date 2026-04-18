"""Resource lookups for the FastAPI `/v1` service API surface.

These helpers keep route handlers thin while preserving the same tenant/app
scoping rules as the legacy service API endpoints.
"""

from __future__ import annotations

from sqlalchemy import select

from api_server.errors import forbidden, not_found
from api_server.models.app import App, AppModelConfig, EndUser, Site, Tenant, Workflow
from api_server.services.webapp_context import WebappContext
from extensions.ext_database import db


class ServiceApiResourceService:
    """Load app-scoped resources for service API routes."""

    @staticmethod
    async def get_site(*, app_id: str) -> Site:
        async with db.session_context() as session:
            site = await session.scalar(select(Site).where(Site.app_id == app_id).limit(1))
        if site is None:
            raise forbidden("site_disabled", "Site is disabled.")
        return site

    @staticmethod
    async def get_end_user(*, tenant_id: str, app_id: str, end_user_id: str) -> EndUser:
        async with db.session_context() as session:
            end_user = await session.scalar(
                select(EndUser).where(
                    EndUser.id == end_user_id,
                    EndUser.tenant_id == tenant_id,
                    EndUser.app_id == app_id,
                )
            )
        if end_user is None:
            raise not_found("end_user_not_found", "End user not found.")
        return end_user

    @staticmethod
    async def build_runtime_context(*, app: App, end_user: EndUser) -> WebappContext:
        async with db.session_context() as session:
            site = await session.scalar(select(Site).where(Site.app_id == app.id).limit(1))
            tenant = await session.scalar(select(Tenant).where(Tenant.id == app.tenant_id).limit(1))

            app_model_config = None
            if app.app_model_config_id:
                app_model_config = await session.scalar(
                    select(AppModelConfig).where(AppModelConfig.id == app.app_model_config_id).limit(1)
                )

            workflow = None
            if app.workflow_id:
                workflow = await session.scalar(select(Workflow).where(Workflow.id == app.workflow_id).limit(1))

        if site is None or tenant is None:
            raise forbidden("app_unavailable", "App unavailable, please check your app configurations.")

        return WebappContext(
            app=app,
            site=site,
            end_user=end_user,
            tenant=tenant,
            app_model_config=app_model_config,
            workflow=workflow,
        )
