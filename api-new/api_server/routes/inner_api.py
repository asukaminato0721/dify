from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from api_server.models.bootstrap import DifySetup
from api_server.errors import ApiError
from configs import dify_config
from extensions.ext_database import db

router = APIRouter(tags=["inner-api"])


class InnerMailPayload(BaseModel):
    to: list[str] = Field(min_length=1)
    subject: str
    body: str
    substitutions: dict[str, Any] | None = None


class WorkspaceCreatePayload(BaseModel):
    name: str
    owner_email: str


class WorkspaceOwnerlessPayload(BaseModel):
    name: str


class InnerAppDSLImportPayload(BaseModel):
    yaml_content: str
    creator_email: str
    name: str | None = None
    description: str | None = None


async def _ensure_setup() -> None:
    if dify_config.EDITION != "SELF_HOSTED":
        return
    async with db.session_context() as session:
        setup = await session.scalar(select(DifySetup).limit(1))
    if setup is None:
        raise ApiError(status_code=404, code="not_setup", message="Dify is not initialized.")


def _check_inner_api_access(expected_key: str | None, header_key: str | None, *, require_flag: bool = True) -> None:
    if require_flag and not dify_config.INNER_API:
        raise ApiError(status_code=404, code="not_found", message="Not found.")
    if not header_key or not expected_key or header_key != expected_key:
        raise ApiError(status_code=401, code="unauthorized", message="Unauthorized.")


def _queue_inner_email(payload: InnerMailPayload) -> dict[str, str]:
    from tasks.mail_inner_task import send_inner_email_task

    delay = cast(Any, send_inner_email_task).delay
    delay(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        substitutions=payload.substitutions,
    )
    return {"message": "success"}


def _create_enterprise_workspace(payload: WorkspaceCreatePayload) -> tuple[dict[str, Any], int]:
    from core.db.session_factory import create_sync_session
    from events.tenant_event import tenant_was_created
    from models import Account
    from services.account_service import TenantService

    with create_sync_session() as session:
        account = session.scalar(select(Account).where(Account.email == payload.owner_email).limit(1))
        if account is None:
            return {"message": "owner account not found."}, 404

        tenant = TenantService.create_tenant(payload.name, is_from_dashboard=True)
        TenantService.create_tenant_member(tenant, account, role="owner")
        tenant_was_created.send(tenant)

    return {
            "message": "enterprise workspace created.",
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "plan": tenant.plan,
                "status": tenant.status,
                "created_at": tenant.created_at.isoformat() + "Z" if tenant.created_at else None,
                "updated_at": tenant.updated_at.isoformat() + "Z" if tenant.updated_at else None,
            },
        }, 200


def _create_enterprise_workspace_ownerless(payload: WorkspaceOwnerlessPayload) -> dict[str, Any]:
    from events.tenant_event import tenant_was_created
    from services.account_service import TenantService

    tenant = TenantService.create_tenant(payload.name, is_from_dashboard=True)
    tenant_was_created.send(tenant)

    return {
        "message": "enterprise workspace created.",
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "encrypt_public_key": tenant.encrypt_public_key,
            "plan": tenant.plan,
            "status": tenant.status,
            "custom_config": json.loads(tenant.custom_config) if tenant.custom_config else {},
            "created_at": tenant.created_at.isoformat() + "Z" if tenant.created_at else None,
            "updated_at": tenant.updated_at.isoformat() + "Z" if tenant.updated_at else None,
        },
    }


def _import_app_dsl(workspace_id: str, payload: InnerAppDSLImportPayload) -> tuple[dict[str, Any], int]:
    from core.db.session_factory import create_sync_session
    from models import Account
    from models.account import AccountStatus
    from services.app_dsl_service import AppDslService
    from services.entities.dsl_entities import ImportStatus

    with create_sync_session() as session:
        account = session.scalar(select(Account).where(Account.email == payload.creator_email).limit(1))
        if account is None or account.status != AccountStatus.ACTIVE:
            return {"message": f"account '{payload.creator_email}' not found or inactive"}, 404

        account.set_tenant_id(workspace_id)
        dsl_service = AppDslService(cast(Any, session))
        result = dsl_service.import_app(
            account=account,
            import_mode="yaml-content",
            yaml_content=payload.yaml_content,
            name=payload.name,
            description=payload.description,
        )
        if result.status == ImportStatus.FAILED:
            session.rollback()
            return result.model_dump(mode="json"), 400
        session.commit()
        if result.status == ImportStatus.PENDING:
            return result.model_dump(mode="json"), 202
        return result.model_dump(mode="json"), 200
    raise AssertionError("unreachable")


def _export_app_dsl(app_id: str, *, include_secret: bool) -> tuple[dict[str, Any], int]:
    from core.db.session_factory import create_sync_session
    from models import App
    from services.app_dsl_service import AppDslService

    with create_sync_session() as session:
        app_model = session.get(App, app_id)
        if not app_model:
            return {"message": "app not found"}, 404
        data = AppDslService.export_dsl(app_model=app_model, include_secret=include_secret)
    return {"data": data}, 200


@router.post("/inner/api/enterprise/mail")
async def send_enterprise_mail(
    payload: InnerMailPayload,
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> dict[str, str]:
    await _ensure_setup()
    _check_inner_api_access(dify_config.INNER_API_KEY, x_inner_api_key)
    return await asyncio.to_thread(_queue_inner_email, payload)


@router.post("/inner/api/billing/mail")
async def send_billing_mail(
    payload: InnerMailPayload,
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> dict[str, str]:
    await _ensure_setup()
    _check_inner_api_access(dify_config.INNER_API_KEY, x_inner_api_key)
    return await asyncio.to_thread(_queue_inner_email, payload)


@router.post("/inner/api/enterprise/workspace")
async def create_enterprise_workspace(
    payload: WorkspaceCreatePayload,
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    await _ensure_setup()
    _check_inner_api_access(dify_config.INNER_API_KEY, x_inner_api_key)
    body, status_code = await asyncio.to_thread(_create_enterprise_workspace, payload)
    return JSONResponse(status_code=status_code, content=body)


@router.post("/inner/api/enterprise/workspace/ownerless")
async def create_enterprise_workspace_ownerless(
    payload: WorkspaceOwnerlessPayload,
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> dict[str, Any]:
    await _ensure_setup()
    _check_inner_api_access(dify_config.INNER_API_KEY, x_inner_api_key)
    return await asyncio.to_thread(_create_enterprise_workspace_ownerless, payload)


@router.post("/inner/api/enterprise/workspaces/{workspace_id}/dsl/import")
async def import_enterprise_app_dsl(
    workspace_id: str,
    payload: InnerAppDSLImportPayload,
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    await _ensure_setup()
    _check_inner_api_access(dify_config.INNER_API_KEY, x_inner_api_key)
    body, status_code = await asyncio.to_thread(_import_app_dsl, workspace_id, payload)
    return JSONResponse(status_code=status_code, content=body)


@router.get("/inner/api/enterprise/apps/{app_id}/dsl")
async def export_enterprise_app_dsl(
    app_id: str,
    include_secret: bool = Query(default=False),
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    await _ensure_setup()
    _check_inner_api_access(dify_config.INNER_API_KEY, x_inner_api_key)
    body, status_code = await asyncio.to_thread(_export_app_dsl, app_id, include_secret=include_secret)
    return JSONResponse(status_code=status_code, content=body)
