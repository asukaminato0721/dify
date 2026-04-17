"""FastAPI public human-input form routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_server.services.human_input_forms import FormDefinitionResponseDict, HumanInputFormService
from configs import dify_config

router = APIRouter(tags=["human-input"])


class HumanInputFormSubmitPayload(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    action: str


@router.get("/api/form/human_input/{form_token}")
async def get_human_input_form(request: Request, form_token: str) -> FormDefinitionResponseDict:
    ip_address = HumanInputFormService.extract_remote_ip(
        forwarded_for=request.headers.get("X-Forwarded-For"),
        cf_connecting_ip=request.headers.get("CF-Connecting-IP"),
        client_host=request.client.host if request.client else None,
    )
    HumanInputFormService.check_rate_limit(
        prefix="web_form_access_rate_limit",
        max_attempts=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_MAX_ATTEMPTS,
        time_window=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_WINDOW_SECONDS,
        ip_address=ip_address,
    )
    return await HumanInputFormService.get_form_definition_response(form_token=form_token)


@router.post("/api/form/human_input/{form_token}")
async def submit_human_input_form(
    request: Request,
    form_token: str,
    payload: HumanInputFormSubmitPayload,
) -> dict[str, Any]:
    ip_address = HumanInputFormService.extract_remote_ip(
        forwarded_for=request.headers.get("X-Forwarded-For"),
        cf_connecting_ip=request.headers.get("CF-Connecting-IP"),
        client_host=request.client.host if request.client else None,
    )
    HumanInputFormService.check_rate_limit(
        prefix="web_form_submit_rate_limit",
        max_attempts=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_MAX_ATTEMPTS,
        time_window=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_WINDOW_SECONDS,
        ip_address=ip_address,
    )
    await HumanInputFormService.submit_form_by_token(
        form_token=form_token,
        selected_action_id=payload.action,
        form_data=payload.inputs,
    )
    return {}
