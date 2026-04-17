from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select

from api_server.auth import extract_webapp_passport, verify_passport
from api_server.errors import bad_request, forbidden, unauthorized
from api_server.models.app import App, AppModelConfig, EndUser, Site, Tenant, Workflow
from extensions.ext_database import db


@dataclass(slots=True)
class WebappContext:
    app: App
    site: Site
    end_user: EndUser
    tenant: Tenant
    app_model_config: AppModelConfig | None
    workflow: Workflow | None


class WebappContextService:
    """Resolve public webapp context from the webapp passport token."""

    @staticmethod
    async def resolve(request: Request, expected_user_id: str | None = None) -> WebappContext:
        header_app_code = request.headers.get("X-App-Code")
        passport = await extract_webapp_passport(header_app_code or "", request)
        if not passport:
            raise unauthorized("missing_passport", "App token is missing.")

        try:
            decoded = verify_passport(passport)
        except Exception:
            raise unauthorized("invalid_passport", "Invalid token.")

        app_id = decoded.get("app_id")
        app_code = decoded.get("app_code") or header_app_code
        end_user_id = decoded.get("end_user_id")
        if not isinstance(app_id, str) or not isinstance(app_code, str) or not isinstance(end_user_id, str):
            raise unauthorized("invalid_passport", "Invalid token.")

        async with db.session_context() as session:
            app = await session.scalar(select(App).where(App.id == app_id).limit(1))
            site = await session.scalar(select(Site).where(Site.code == app_code).limit(1))
            end_user = await session.scalar(select(EndUser).where(EndUser.id == end_user_id).limit(1))

            if app is None or site is None or end_user is None:
                raise bad_request("not_found", "Site URL is no longer valid.")
            if site.app_id != app.id:
                raise bad_request("not_found", "Site URL is no longer valid.")
            if not app.enable_site:
                raise forbidden("site_disabled", "Site is disabled.")

            tenant = await session.scalar(select(Tenant).where(Tenant.id == app.tenant_id).limit(1))
            if tenant is None:
                raise bad_request("not_found", "Workspace not found.")

            app_model_config = None
            if app.app_model_config_id:
                app_model_config = await session.scalar(
                    select(AppModelConfig).where(AppModelConfig.id == app.app_model_config_id).limit(1)
                )

            workflow = None
            if app.workflow_id:
                workflow = await session.scalar(select(Workflow).where(Workflow.id == app.workflow_id).limit(1))

        if expected_user_id is not None and end_user.session_id != expected_user_id:
            raise unauthorized("invalid_passport", "Authentication has expired.")

        return WebappContext(
            app=app,
            site=site,
            end_user=end_user,
            tenant=tenant,
            app_model_config=app_model_config,
            workflow=workflow,
        )
