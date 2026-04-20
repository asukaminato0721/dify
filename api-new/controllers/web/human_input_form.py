"""
Web App Human Input Form APIs.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, NotRequired, TypedDict

from api_server.errors import ApiError
from api_server.services.human_input_forms import HumanInputFormService
from flask_restx import Resource
from pydantic import BaseModel
from sqlalchemy import select

from configs import dify_config
from controllers.web import web_ns
from controllers.web.error import NotFoundError, WebFormRateLimitExceededError
from extensions.ext_database import db
from flask import Response, current_app, request
from libs.helper import RateLimiter, extract_remote_ip
from models.account import TenantStatus
from models.model import App, Site
from services.human_input_service import Form
from werkzeug.exceptions import Forbidden

logger = logging.getLogger(__name__)


class HumanInputFormSubmitPayload(BaseModel):
    inputs: dict
    action: str


_FORM_SUBMIT_RATE_LIMITER = RateLimiter(
    prefix="web_form_submit_rate_limit",
    max_attempts=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_MAX_ATTEMPTS,
    time_window=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_WINDOW_SECONDS,
)
_FORM_ACCESS_RATE_LIMITER = RateLimiter(
    prefix="web_form_access_rate_limit",
    max_attempts=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_MAX_ATTEMPTS,
    time_window=dify_config.WEB_FORM_SUBMIT_RATE_LIMIT_WINDOW_SECONDS,
)


def _stringify_default_values(values: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, (dict, list)):
            result[key] = json.dumps(value, ensure_ascii=False)
        else:
            result[key] = str(value)
    return result


def _to_timestamp(value: datetime) -> int:
    return int(value.timestamp())


class FormDefinitionPayload(TypedDict):
    form_content: Any
    inputs: Any
    resolved_default_values: dict[str, str]
    user_actions: Any
    expiration_time: int
    site: NotRequired[dict]


def _jsonify_form_definition(form: Form, site_payload: dict | None = None) -> Any:
    """Return the form payload (optionally with site) as a JSON response."""
    definition_payload = form.get_definition().model_dump()
    payload: FormDefinitionPayload = {
        "form_content": definition_payload["rendered_content"],
        "inputs": definition_payload["inputs"],
        "resolved_default_values": _stringify_default_values(definition_payload["default_values"]),
        "user_actions": definition_payload["user_actions"],
        "expiration_time": _to_timestamp(form.expiration_time),
    }
    if site_payload is not None:
        payload["site"] = site_payload
    return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json")


@web_ns.route("/form/human_input/<string:form_token>")
class HumanInputFormApi(Resource):
    """API for getting and submitting human input forms via the web app."""

    # NOTE(QuantumGhost): this endpoint is unauthenticated on purpose for now.

    # def get(self, _app_model: App, _end_user: EndUser, form_token: str):
    def get(self, form_token: str):
        """
        Get human input form definition by token.

        GET /api/form/human_input/<form_token>
        """
        ip_address = extract_remote_ip(request)
        if _FORM_ACCESS_RATE_LIMITER.is_rate_limited(ip_address):
            raise WebFormRateLimitExceededError()
        _FORM_ACCESS_RATE_LIMITER.increment_rate_limit(ip_address)

        try:
            payload = asyncio.run(HumanInputFormService.get_form_definition_response(form_token=form_token))
        except ApiError as api_error:
            if api_error.status_code == 404:
                raise NotFoundError("Form not found")
            if api_error.status_code == 429:
                raise WebFormRateLimitExceededError()
            if api_error.status_code == 403:
                raise Forbidden()
            raise

        return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json")

    # def post(self, _app_model: App, _end_user: EndUser, form_token: str):
    def post(self, form_token: str):
        """
        Submit human input form by token.

        POST /api/form/human_input/<form_token>

        Request body:
        {
            "inputs": {
                "content": "User input content"
            },
            "action": "Approve"
        }
        """
        payload = HumanInputFormSubmitPayload.model_validate(request.get_json())

        ip_address = extract_remote_ip(request)
        if _FORM_SUBMIT_RATE_LIMITER.is_rate_limited(ip_address):
            raise WebFormRateLimitExceededError()
        _FORM_SUBMIT_RATE_LIMITER.increment_rate_limit(ip_address)

        try:
            asyncio.run(
                HumanInputFormService.submit_form_by_token(
                    form_token=form_token,
                    selected_action_id=payload.action,
                    form_data=payload.inputs,
                )
            )
        except ApiError as api_error:
            if api_error.status_code == 404:
                raise NotFoundError("Form not found")
            if api_error.status_code == 429:
                raise WebFormRateLimitExceededError()
            if api_error.status_code == 403:
                raise Forbidden()
            raise

        return {}, 200


async def _get_app_site_from_form(form: Form) -> tuple[App, Site]:
    """Resolve App/Site for the form's app and validate tenant status."""
    async with db.session_context() as session:
        app_model = await session.scalar(select(App).where(App.id == form.app_id))
        if app_model is None or app_model.tenant_id != form.tenant_id:
            raise NotFoundError("Form not found")
        await session.refresh(app_model, attribute_names=["tenant"])

        site = await session.scalar(select(Site).where(Site.app_id == app_model.id).limit(1))
        if site is None:
            raise Forbidden()

    if app_model.tenant and app_model.tenant.status == TenantStatus.ARCHIVE:
        raise Forbidden()

    return app_model, site
