from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from api_server.errors import ApiError
from api_server.models.bootstrap import DifySetup
from configs import dify_config
from extensions.ext_database import db
from libs.passport import PassportService
from libs.token import extract_access_token
from services.account_service import AccountService
from services.feature_service import FeatureService
from core.schemas.schema_manager import SchemaManager

router = APIRouter(tags=["console"])


async def _ensure_console_setup() -> None:
    if dify_config.EDITION != "SELF_HOSTED":
        return
    async with db.session_context() as session:
        setup = await session.scalar(select(DifySetup).limit(1))
    if setup is None:
        raise ApiError(status_code=404, code="not_setup", message="Dify is not initialized.")


async def _resolve_console_account(request: Request):
    token = extract_access_token(request)
    if not token:
        raise ApiError(status_code=401, code="unauthorized", message="Unauthorized.")
    try:
        decoded = PassportService().verify(token)
    except Exception as exc:
        raise ApiError(status_code=401, code="unauthorized", message="Unauthorized.") from exc
    user_id = decoded.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise ApiError(status_code=401, code="unauthorized", message="Unauthorized.")

    account = await asyncio.to_thread(AccountService.load_user, user_id)
    if account is None or account.current_tenant_id is None:
        raise ApiError(status_code=401, code="unauthorized", message="Unauthorized.")
    return account


@router.get("/console/api/features")
async def get_console_features(request: Request) -> dict[str, Any]:
    await _ensure_console_setup()
    account = await _resolve_console_account(request)
    return await asyncio.to_thread(lambda: FeatureService.get_features(account.current_tenant_id).model_dump())  # type: ignore[arg-type]


@router.get("/console/api/spec/schema-definitions")
async def get_console_schema_definitions(request: Request) -> list[dict[str, Any]]:
    await _ensure_console_setup()
    await _resolve_console_account(request)

    def _load() -> list[dict[str, Any]]:
        try:
            return [dict(item) for item in SchemaManager().get_all_schema_definitions()]
        except Exception:
            return []

    return await asyncio.to_thread(_load)
