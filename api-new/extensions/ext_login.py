import json
from datetime import timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

import flask_login
from configs import dify_config
from constants import HEADER_NAME_APP_CODE
from core.db.session_factory import session_factory
from dify_app import DifyApp
from flask import Request, request
from flask import Response as FlaskResponse
from flask_login import user_loaded_from_request, user_logged_in
from libs.datetime_utils import naive_utc_now
from libs.passport import PassportService
from libs.token import extract_access_token, extract_webapp_passport
from models import Account, Tenant, TenantAccountJoin
from models.account import AccountStatus
from models.model import AppMCPServer, EndUser
from werkzeug.exceptions import NotFound, Unauthorized

type LoginUser = Account | EndUser


class DifyLoginManager(flask_login.LoginManager):
    """Project-specific Flask-Login manager with a stable unauthorized contract.

    Dify registers `unauthorized_handler` below to always return a JSON `Response`.
    Overriding this method lets callers rely on that narrower return type instead of
    Flask-Login's broader callback contract.
    """

    def unauthorized(self) -> FlaskResponse:
        """Return the registered unauthorized handler result as a Flask `Response`."""
        return cast(FlaskResponse, super().unauthorized())

    def load_user_from_request_context(self) -> None:
        """Populate Flask-Login's request-local user cache for the current request."""
        self._load_user()


login_manager = DifyLoginManager()


def _load_end_user(session: Session, end_user_id: str) -> EndUser:
    """Resolve an end-user through the sync auth compatibility session."""
    end_user = session.scalar(select(EndUser).where(EndUser.id == end_user_id))
    if not end_user:
        raise NotFound("End user not found.")
    return end_user


def _load_logged_in_account(session: Session, account_id: str) -> Account:
    """Load console auth users through the sync compatibility session.

    Flask-Login's request hook is still synchronous in this compatibility
    layer, so auth has to use the configured sync session backed by
    `AsyncEngine.sync_engine` until the request loader is replaced.
    """

    account = session.get(Account, account_id)
    if not account:
        raise Unauthorized("Invalid Authorization token.")
    if account.status == AccountStatus.BANNED:
        raise Unauthorized("Account is banned.")

    current_tenant = session.scalar(
        select(TenantAccountJoin)
        .where(TenantAccountJoin.account_id == account.id, TenantAccountJoin.current == True)
        .limit(1)
    )
    if current_tenant:
        account.set_tenant_id(current_tenant.tenant_id)
    else:
        available_ta = session.scalar(
            select(TenantAccountJoin)
            .where(TenantAccountJoin.account_id == account.id)
            .order_by(TenantAccountJoin.id.asc())
            .limit(1)
        )
        if not available_ta:
            raise Unauthorized("Invalid Authorization token.")
        account.set_tenant_id(available_ta.tenant_id)
        available_ta.current = True
        session.commit()

    if naive_utc_now() - account.last_active_at > timedelta(minutes=10):
        account.last_active_at = naive_utc_now()
        session.commit()
    session.refresh(account)
    return account


# Flask-Login configuration
@login_manager.request_loader
def load_user_from_request(request_from_flask_login: Request) -> LoginUser | None:
    """Load user based on the request."""
    del request_from_flask_login

    # Skip authentication for documentation endpoints
    if dify_config.SWAGGER_UI_ENABLED and request.path.endswith((dify_config.SWAGGER_UI_PATH, "/swagger.json")):
        return None

    auth_token = extract_access_token(request)

    # Check for admin API key authentication first
    if dify_config.ADMIN_API_KEY_ENABLE and auth_token:
        admin_api_key = dify_config.ADMIN_API_KEY
        if admin_api_key and admin_api_key == auth_token:
            workspace_id = request.headers.get("X-WORKSPACE-ID")
            if workspace_id:
                with session_factory.create_sync_session() as session:
                    tenant_account_join = session.execute(
                        select(Tenant, TenantAccountJoin)
                        .where(Tenant.id == workspace_id)
                        .where(TenantAccountJoin.tenant_id == Tenant.id)
                        .where(TenantAccountJoin.role == "owner")
                    ).one_or_none()
                    if tenant_account_join:
                        tenant, ta = tenant_account_join
                        account = session.scalar(select(Account).where(Account.id == ta.account_id))
                        if account:
                            account.current_tenant = tenant
                            return account

    if request.blueprint in {"console", "inner_api"}:
        if not auth_token:
            raise Unauthorized("Invalid Authorization token.")
        decoded = PassportService().verify(auth_token)
        user_id = decoded.get("user_id")
        source = decoded.get("token_source")
        if source:
            raise Unauthorized("Invalid Authorization token.")
        if not user_id:
            raise Unauthorized("Invalid Authorization token.")
        with session_factory.create_sync_session() as session:
            return _load_logged_in_account(session, user_id)
    elif request.blueprint == "web":
        app_code = request.headers.get(HEADER_NAME_APP_CODE)
        webapp_token = extract_webapp_passport(app_code, request) if app_code else None

        if webapp_token:
            decoded = PassportService().verify(webapp_token)
            end_user_id = decoded.get("end_user_id")
            if not end_user_id:
                raise Unauthorized("Invalid Authorization token.")
            with session_factory.create_sync_session() as session:
                return _load_end_user(session, end_user_id)
        else:
            if not auth_token:
                raise Unauthorized("Invalid Authorization token.")
            decoded = PassportService().verify(auth_token)
            end_user_id = decoded.get("end_user_id")
            if end_user_id:
                with session_factory.create_sync_session() as session:
                    return _load_end_user(session, end_user_id)
            else:
                raise Unauthorized("Invalid Authorization token for web API.")
    elif request.blueprint == "mcp":
        server_code = request.view_args.get("server_code") if request.view_args else None
        if not server_code:
            raise Unauthorized("Invalid Authorization token.")
        with session_factory.create_sync_session() as session:
            app_mcp_server = session.scalar(
                select(AppMCPServer).where(AppMCPServer.server_code == server_code).limit(1)
            )
            if not app_mcp_server:
                raise NotFound("App MCP server not found.")
            end_user = session.scalar(
                select(EndUser).where(EndUser.session_id == app_mcp_server.id, EndUser.type == "mcp").limit(1)
            )
            if not end_user:
                raise NotFound("End user not found.")
            return end_user

    return None


@user_logged_in.connect
@user_loaded_from_request.connect
def on_user_logged_in(_sender: object, user: LoginUser) -> None:
    """Called when a user logged in.

    Note: AccountService.load_logged_in_account will populate user.current_tenant_id
    through the load_user method, which calls account.set_tenant_id().
    """
    # tenant_id context variable removed - using current_user.current_tenant_id directly
    pass


@login_manager.unauthorized_handler
def unauthorized_handler() -> FlaskResponse:
    """Handle unauthorized requests."""
    # Keep this as a concrete `Response`; `DifyLoginManager.unauthorized()` narrows
    # Flask-Login's callback contract based on this override.
    return cast(
        FlaskResponse,
        FlaskResponse(
            json.dumps({"code": "unauthorized", "message": "Unauthorized."}),
            status=401,
            content_type="application/json",
        ),
    )


def init_app(app: DifyApp) -> None:
    login_manager.init_app(app)
