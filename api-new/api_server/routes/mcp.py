from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from api_server.errors import bad_request, not_found
from core.mcp import types as mcp_types
from core.mcp.server.streamable_http import handle_mcp_request
from graphon.variables.input_entities import VariableEntity, VariableEntityType
from models.enums import AppMCPServerStatus
from models.model import App, AppMCPServer, AppMode, EndUser
from core.db.session_factory import get_sync_session_maker

router = APIRouter(tags=["mcp"])


class MCPRequestPayload(BaseModel):
    jsonrpc: str = Field(description="JSON-RPC version (should be '2.0')")
    method: str = Field(description="The method to invoke")
    params: dict[str, Any] | None = Field(default=None, description="Parameters for the method")
    id: int | str | None = Field(default=None, description="Request ID for tracking responses")


def _parse_mcp_request(args: dict[str, Any]) -> mcp_types.ClientRequest | mcp_types.ClientNotification:
    try:
        return mcp_types.ClientRequest.model_validate(args)
    except ValidationError:
        try:
            return mcp_types.ClientNotification.model_validate(args)
        except ValidationError as exc:
            raise bad_request("invalid_mcp_request", f"Invalid MCP request: {str(exc)}") from exc


def _load_mcp_server_and_app_sync(server_code: str) -> tuple[AppMCPServer, App]:
    with get_sync_session_maker().begin() as session:
        mcp_server = session.scalar(select(AppMCPServer).where(AppMCPServer.server_code == server_code).limit(1))
        if not mcp_server:
            raise not_found("server_not_found", "Server Not Found")

        app = session.scalar(select(App).where(App.id == mcp_server.app_id).limit(1))
        if not app:
            raise not_found("app_not_found", "App Not Found")

    if mcp_server.status != AppMCPServerStatus.ACTIVE:
        raise bad_request("server_inactive", "Server is not active")

    return mcp_server, app


async def _load_mcp_server_and_app(server_code: str) -> tuple[AppMCPServer, App]:
    return await asyncio.to_thread(_load_mcp_server_and_app_sync, server_code)


def _create_variable_entity(item: dict[str, Any]) -> VariableEntity:
    variable_type_raw: str = item.get("type", "") or list(item.keys())[0]
    try:
        variable_type = VariableEntityType(variable_type_raw)
    except ValueError as exc:
        raise bad_request("invalid_mcp_params", f"Invalid user_input_form variable type: {variable_type_raw}") from exc
    variable = item[variable_type_raw]

    return VariableEntity(
        type=variable_type,
        variable=variable.get("variable"),
        description=variable.get("description") or "",
        label=variable.get("label"),
        required=variable.get("required", False),
        max_length=variable.get("max_length"),
        options=variable.get("options") or [],
        json_schema=variable.get("json_schema"),
    )


def _get_user_input_form_sync(app: App) -> list[VariableEntity]:
    if app.mode in {AppMode.ADVANCED_CHAT, AppMode.WORKFLOW}:
        if not app.workflow:
            raise bad_request("app_unavailable", "App is unavailable")
        raw_user_input_form = app.workflow.user_input_form(to_old_structure=True)
    else:
        if not app.app_model_config:
            raise bad_request("app_unavailable", "App is unavailable")
        features_dict = app.app_model_config.to_dict()
        raw_user_input_form = features_dict.get("user_input_form", [])

    return [_create_variable_entity(item) for item in raw_user_input_form]


async def _get_user_input_form(app: App) -> list[VariableEntity]:
    return await asyncio.to_thread(_get_user_input_form_sync, app)


def _retrieve_end_user_sync(tenant_id: str, mcp_server_id: str) -> EndUser | None:
    with get_sync_session_maker().begin() as session:
        return session.scalar(
            select(EndUser)
            .where(EndUser.tenant_id == tenant_id)
            .where(EndUser.session_id == mcp_server_id)
            .where(EndUser.type == "mcp")
            .limit(1)
        )


async def _retrieve_end_user(tenant_id: str, mcp_server_id: str) -> EndUser | None:
    return await asyncio.to_thread(_retrieve_end_user_sync, tenant_id, mcp_server_id)


def _create_end_user_sync(client_name: str, tenant_id: str, app_id: str, mcp_server_id: str) -> EndUser:
    with get_sync_session_maker().begin() as session:
        end_user = EndUser(
            tenant_id=tenant_id,
            app_id=app_id,
            type="mcp",
            name=client_name,
            session_id=mcp_server_id,
        )
        session.add(end_user)
        session.flush()
        session.refresh(end_user)
    return end_user


async def _create_end_user(client_name: str, tenant_id: str, app_id: str, mcp_server_id: str) -> EndUser:
    return await asyncio.to_thread(_create_end_user_sync, client_name, tenant_id, app_id, mcp_server_id)


@router.post("/mcp/server/{server_code}/mcp")
async def handle_mcp_server_request(server_code: str, payload: MCPRequestPayload) -> Response:
    request_id = payload.id
    mcp_request = _parse_mcp_request(payload.model_dump(exclude_none=True))
    mcp_server, app = await _load_mcp_server_and_app(server_code)
    user_input_form = await _get_user_input_form(app)

    if isinstance(mcp_request, mcp_types.ClientNotification):
        if mcp_request.root.method != "notifications/initialized":
            raise bad_request("invalid_mcp_request", "Invalid notification method")
        return Response(status_code=202, media_type="application/json")

    if request_id is None:
        raise bad_request("invalid_mcp_request", "Request ID is required")

    end_user = await _retrieve_end_user(mcp_server.tenant_id, mcp_server.id)
    if not end_user and isinstance(mcp_request.root, mcp_types.InitializeRequest):
        client_info = mcp_request.root.params.clientInfo
        client_name = f"{client_info.name}@{client_info.version}"
        end_user = await _create_end_user(client_name, app.tenant_id, app.id, mcp_server.id)

    result = await asyncio.to_thread(handle_mcp_request, app, mcp_request, user_input_form, mcp_server, end_user, request_id)
    return JSONResponse(content=result.model_dump(by_alias=True, mode="json", exclude_none=True))
