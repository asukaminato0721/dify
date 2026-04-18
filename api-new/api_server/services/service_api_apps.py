"""FastAPI-native app-info services for the `/v1` service API surface.

These helpers mirror the legacy service API app metadata endpoints while staying
inside the local async ORM layer. The methods intentionally fetch only the data
needed by currently mounted routes so the port can advance incrementally.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

from sqlalchemy import select

from api_server.errors import bad_request
from api_server.models.app import Account, ApiToolProvider, App, AppModelConfig, Tag, TagBinding, TagType, Workflow
from configs import dify_config
from core.app.app_config.common.parameters_mapping import AppParametersDict, get_parameters_from_feature_dict
from extensions.ext_database import db


class ToolIconsResponseDict(TypedDict):
    tool_icons: dict[str, Any]


class AppInfoResponseDict(TypedDict):
    name: str
    description: str
    tags: list[str]
    mode: str
    author_name: str | None


class ServiceApiAppService:
    """Load app-scoped metadata for FastAPI service API routes."""

    @staticmethod
    async def get_parameters(*, app: App) -> AppParametersDict:
        if app.mode.value in {"advanced-chat", "workflow"}:
            if app.workflow_id is None:
                raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

            async with db.session_context() as session:
                workflow = await session.scalar(select(Workflow).where(Workflow.id == app.workflow_id).limit(1))
            if workflow is None:
                raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

            return get_parameters_from_feature_dict(
                features_dict=workflow.features_dict,
                user_input_form=workflow.user_input_form(to_old_structure=True),
            )

        if app.app_model_config_id is None:
            raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

        async with db.session_context() as session:
            app_model_config = await session.scalar(
                select(AppModelConfig).where(AppModelConfig.id == app.app_model_config_id).limit(1)
            )
        if app_model_config is None:
            raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

        features_dict = cast(dict[str, Any], app_model_config.to_feature_dict())
        return get_parameters_from_feature_dict(
            features_dict=features_dict,
            user_input_form=features_dict.get("user_input_form", []),
        )

    @staticmethod
    async def get_meta(*, app: App) -> ToolIconsResponseDict:
        meta: ToolIconsResponseDict = {"tool_icons": {}}

        tools: list[dict[str, Any]]
        if app.mode.value in {"advanced-chat", "workflow"}:
            if app.workflow_id is None:
                return meta

            async with db.session_context() as session:
                workflow = await session.scalar(select(Workflow).where(Workflow.id == app.workflow_id).limit(1))
            if workflow is None:
                return meta

            nodes = workflow.graph_dict.get("nodes", [])
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
            if app.app_model_config_id is None:
                return meta

            async with db.session_context() as session:
                app_model_config = await session.scalar(
                    select(AppModelConfig).where(AppModelConfig.id == app.app_model_config_id).limit(1)
                )
            if app_model_config is None:
                return meta

            agent_mode = app_model_config.to_feature_dict().get("agent_mode", {})
            tools = cast(list[dict[str, Any]], agent_mode.get("tools", []))

        url_prefix = dify_config.CONSOLE_API_URL + "/console/api/workspaces/current/tool-provider/builtin/"
        api_provider_ids = [
            str(tool.get("provider_id"))
            for tool in tools
            if tool.get("provider_type") == "api" and tool.get("provider_id")
        ]

        provider_icons_by_id: dict[str, str] = {}
        if api_provider_ids:
            async with db.session_context() as session:
                provider_rows = (
                    await session.scalars(select(ApiToolProvider).where(ApiToolProvider.id.in_(api_provider_ids)))
                ).all()
            provider_icons_by_id = {provider.id: provider.icon for provider in provider_rows}

        for tool in tools:
            provider_type = str(tool.get("provider_type") or "")
            provider_id = str(tool.get("provider_id") or "")
            tool_name = str(tool.get("tool_name") or "")
            if not tool_name or not provider_type:
                continue

            if provider_type == "builtin":
                meta["tool_icons"][tool_name] = url_prefix + provider_id + "/icon"
                continue

            if provider_type == "api":
                icon = provider_icons_by_id.get(provider_id)
                if icon:
                    try:
                        meta["tool_icons"][tool_name] = json.loads(icon)
                    except json.JSONDecodeError:
                        meta["tool_icons"][tool_name] = {"background": "#252525", "content": "\ud83d\ude01"}
                else:
                    meta["tool_icons"][tool_name] = {"background": "#252525", "content": "\ud83d\ude01"}

        return meta

    @staticmethod
    async def get_info(*, app: App) -> AppInfoResponseDict:
        async with db.session_context() as session:
            tags = (
                await session.scalars(
                    select(Tag)
                    .join(TagBinding, Tag.id == TagBinding.tag_id)
                    .where(
                        TagBinding.target_id == app.id,
                        TagBinding.tenant_id == app.tenant_id,
                        Tag.tenant_id == app.tenant_id,
                        Tag.type == TagType.APP,
                    )
                )
            ).all()

            author_name: str | None = None
            if app.created_by:
                account = await session.scalar(select(Account).where(Account.id == app.created_by).limit(1))
                if account is not None:
                    author_name = account.name

        return {
            "name": app.name,
            "description": app.description,
            "tags": [tag.name for tag in tags],
            "mode": app.mode.value,
            "author_name": author_name,
        }
