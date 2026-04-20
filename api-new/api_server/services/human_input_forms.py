"""FastAPI-native human-input form service.

This service reimplements the public standalone form token flow with async
SQLAlchemy so webapp users can fetch and submit forms without depending on the
legacy Flask repositories.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import import_module
from typing import Any, NotRequired, TypedDict

from sqlalchemy import select

from api_server.errors import bad_request, forbidden, not_found, precondition_failed, too_many_requests
from api_server.models.app import App, Site, Tenant
from api_server.models.human_input import HumanInputForm, HumanInputFormRecipient
from api_server.services.broker_dispatch import apply_async_task
from configs import dify_config
from extensions.ext_database import db
from extensions.ext_redis import async_redis_client
from graphon.nodes.human_input.entities import FormDefinition, validate_human_input_submission
from graphon.nodes.human_input.enums import HumanInputFormKind, HumanInputFormStatus
from libs.datetime_utils import ensure_naive_utc, naive_utc_now

logger = logging.getLogger(__name__)


class SitePayloadDict(TypedDict):
    title: str
    chat_color_theme: str | None
    chat_color_theme_inverted: bool
    icon_type: str | None
    icon: str | None
    icon_background: str | None
    icon_url: str | None
    description: str | None
    copyright: str | None
    privacy_policy: str | None
    custom_disclaimer: str | None
    default_language: str
    prompt_public: bool
    show_workflow_steps: bool
    use_icon_as_answer_icon: bool


class FormDefinitionResponseDict(TypedDict):
    form_content: str
    inputs: list[dict[str, Any]]
    resolved_default_values: dict[str, str]
    user_actions: list[dict[str, Any]]
    expiration_time: int
    site: NotRequired[SitePayloadDict]


@dataclass(frozen=True, slots=True)
class HumanInputFormRecord:
    form_id: str
    workflow_run_id: str | None
    tenant_id: str
    app_id: str
    form_kind: HumanInputFormKind
    definition: FormDefinition
    created_at: datetime
    expiration_time: datetime
    status: HumanInputFormStatus
    selected_action_id: str | None
    submitted_data: dict[str, Any] | None
    submitted_at: datetime | None
    recipient_id: str
    recipient_type: str

    @property
    def submitted(self) -> bool:
        return self.submitted_at is not None


class HumanInputFormService:
    """Resolve, validate, and submit human-input forms in the FastAPI runtime."""

    @staticmethod
    def _get_rate_limit_key(prefix: str, ip_address: str) -> str:
        return f"{prefix}:{ip_address}"

    @classmethod
    async def check_rate_limit(
        cls, *, prefix: str, max_attempts: int, time_window: int, ip_address: str
    ) -> None:
        key = cls._get_rate_limit_key(prefix, ip_address)
        current_time = int(datetime.now().timestamp())
        window_start_time = current_time - time_window

        await async_redis_client.zremrangebyscore(key, "-inf", window_start_time)
        attempts = await async_redis_client.zcard(key)
        if attempts and int(attempts) >= max_attempts:
            raise too_many_requests("web_form_rate_limit_exceeded", "Too many form requests. Please try again later.")

        await async_redis_client.zadd(key, {f"{current_time}:{key}": current_time})
        await async_redis_client.expire(key, time_window * 2)

    @staticmethod
    def extract_remote_ip(*, forwarded_for: str | None, cf_connecting_ip: str | None, client_host: str | None) -> str:
        if cf_connecting_ip:
            return cf_connecting_ip
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        return client_host or "unknown"

    @staticmethod
    def _stringify_default_values(values: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in values.items():
            if value is None:
                result[key] = ""
            elif isinstance(value, (dict, list)):
                result[key] = json.dumps(value, ensure_ascii=False)
            else:
                result[key] = str(value)
        return result

    @staticmethod
    def _build_definition_payload(
        *,
        definition: FormDefinition,
        expiration_time: datetime,
        site_payload: SitePayloadDict | None,
    ) -> FormDefinitionResponseDict:
        payload: FormDefinitionResponseDict = {
            "form_content": definition.rendered_content,
            "inputs": [item.model_dump(mode="json") for item in definition.inputs],
            "resolved_default_values": HumanInputFormService._stringify_default_values(definition.default_values),
            "user_actions": [item.model_dump(mode="json") for item in definition.user_actions],
            "expiration_time": int(expiration_time.timestamp()),
        }
        if site_payload is not None:
            payload["site"] = site_payload
        return payload

    @staticmethod
    def _parse_definition(form: HumanInputForm) -> FormDefinition:
        definition_payload = json.loads(form.form_definition)
        if "expiration_time" not in definition_payload:
            definition_payload["expiration_time"] = form.expiration_time
        return FormDefinition.model_validate(definition_payload)

    @staticmethod
    def _build_site_payload(*, site: Site) -> SitePayloadDict:
        return {
            "title": site.title,
            "chat_color_theme": site.chat_color_theme,
            "chat_color_theme_inverted": site.chat_color_theme_inverted,
            "icon_type": site.icon_type,
            "icon": site.icon,
            "icon_background": site.icon_background,
            "icon_url": None,
            "description": site.description,
            "copyright": site.copyright,
            "privacy_policy": site.privacy_policy,
            "custom_disclaimer": site.custom_disclaimer,
            "default_language": site.default_language,
            "prompt_public": site.prompt_public,
            "show_workflow_steps": site.show_workflow_steps,
            "use_icon_as_answer_icon": site.use_icon_as_answer_icon,
        }

    @classmethod
    async def get_form_by_token(cls, *, form_token: str) -> HumanInputFormRecord | None:
        async with db.session_context() as session:
            row = await session.execute(
                select(HumanInputForm, HumanInputFormRecipient)
                .join(HumanInputFormRecipient, HumanInputFormRecipient.form_id == HumanInputForm.id)
                .where(HumanInputFormRecipient.access_token == form_token)
                .limit(1)
            )
            result = row.first()

        if result is None:
            return None

        form, recipient = result
        return HumanInputFormRecord(
            form_id=form.id,
            workflow_run_id=form.workflow_run_id,
            tenant_id=form.tenant_id,
            app_id=form.app_id,
            form_kind=form.form_kind,
            definition=cls._parse_definition(form),
            created_at=form.created_at,
            expiration_time=form.expiration_time,
            status=form.status,
            selected_action_id=form.selected_action_id,
            submitted_data=json.loads(form.submitted_data) if form.submitted_data else None,
            submitted_at=form.submitted_at,
            recipient_id=recipient.id,
            recipient_type=recipient.recipient_type,
        )

    @classmethod
    async def get_form_definition_response(cls, *, form_token: str) -> FormDefinitionResponseDict:
        form = await cls.get_form_by_token(form_token=form_token)
        if form is None:
            raise not_found("human_input_form_not_found", "Form not found")

        cls.ensure_form_active(form=form)
        site_payload = await cls.get_site_payload(form=form)
        return cls._build_definition_payload(
            definition=form.definition,
            expiration_time=form.expiration_time,
            site_payload=site_payload,
        )

    @classmethod
    async def get_site_payload(cls, *, form: HumanInputFormRecord) -> SitePayloadDict:
        async with db.session_context() as session:
            app = await session.scalar(
                select(App).where(
                    App.id == form.app_id,
                    App.tenant_id == form.tenant_id,
                ).limit(1)
            )
            if app is None:
                raise not_found("human_input_form_not_found", "Form not found")

            site = await session.scalar(select(Site).where(Site.app_id == app.id).limit(1))
            tenant = await session.scalar(select(Tenant).where(Tenant.id == app.tenant_id).limit(1))

        if site is None:
            raise forbidden("not_found", "Form not found")
        if tenant is None or tenant.status == tenant.status.ARCHIVE:
            raise forbidden("not_found", "Form not found")

        return cls._build_site_payload(site=site)

    @classmethod
    def ensure_form_active(cls, *, form: HumanInputFormRecord) -> None:
        if form.submitted:
            raise precondition_failed(
                "human_input_form_submitted",
                f"This form has already been submitted by another user, form_id={form.form_id}",
            )

        if form.status in {HumanInputFormStatus.TIMEOUT, HumanInputFormStatus.EXPIRED}:
            raise precondition_failed(
                "human_input_form_expired",
                f"This form has expired, form_id={form.form_id}",
            )

        now = naive_utc_now()
        if ensure_naive_utc(form.expiration_time) <= now:
            raise precondition_failed(
                "human_input_form_expired",
                f"This form has expired, form_id={form.form_id}",
            )

        global_timeout_seconds = dify_config.HUMAN_INPUT_GLOBAL_TIMEOUT_SECONDS
        if global_timeout_seconds > 0 and form.workflow_run_id is not None:
            global_deadline = ensure_naive_utc(form.created_at) + timedelta(seconds=global_timeout_seconds)
            if global_deadline <= now:
                raise precondition_failed(
                    "human_input_form_expired",
                    f"This form has expired, form_id={form.form_id}",
                )

    @classmethod
    async def submit_form_by_token(
        cls,
        *,
        form_token: str,
        selected_action_id: str,
        form_data: dict[str, Any],
    ) -> None:
        async with db.session_context() as session:
            row = await session.execute(
                select(HumanInputForm, HumanInputFormRecipient)
                .join(HumanInputFormRecipient, HumanInputFormRecipient.form_id == HumanInputForm.id)
                .where(HumanInputFormRecipient.access_token == form_token)
                .with_for_update()
                .limit(1)
            )
            result = row.first()
            if result is None:
                raise not_found("human_input_form_not_found", "Form not found")

            form, recipient = result
            form_record = HumanInputFormRecord(
                form_id=form.id,
                workflow_run_id=form.workflow_run_id,
                tenant_id=form.tenant_id,
                app_id=form.app_id,
                form_kind=form.form_kind,
                definition=cls._parse_definition(form),
                created_at=form.created_at,
                expiration_time=form.expiration_time,
                status=form.status,
                selected_action_id=form.selected_action_id,
                submitted_data=json.loads(form.submitted_data) if form.submitted_data else None,
                submitted_at=form.submitted_at,
                recipient_id=recipient.id,
                recipient_type=recipient.recipient_type,
            )

            cls.ensure_form_active(form=form_record)
            try:
                validate_human_input_submission(
                    inputs=form_record.definition.inputs,
                    user_actions=form_record.definition.user_actions,
                    selected_action_id=selected_action_id,
                    form_data=form_data,
                )
            except ValueError as exc:
                raise bad_request("invalid_form_data", str(exc)) from exc

            form.selected_action_id = selected_action_id
            form.submitted_data = json.dumps(form_data)
            form.submitted_at = naive_utc_now()
            form.status = HumanInputFormStatus.SUBMITTED
            form.submission_end_user_id = None
            form.submission_user_id = None
            form.completed_by_recipient_id = recipient.id

            await session.flush()

        if form.workflow_run_id and form.form_kind == HumanInputFormKind.RUNTIME:
            await cls.enqueue_resume(workflow_run_id=form.workflow_run_id)

    @staticmethod
    async def enqueue_resume(*, workflow_run_id: str) -> None:
        try:
            workflow_task_module = import_module("tasks.app_generate.workflow_execute_task")
            await apply_async_task(
                workflow_task_module.resume_app_execution,
                kwargs={"payload": {"workflow_run_id": workflow_run_id}},
            )
        except Exception:
            logger.exception("Failed to enqueue resume task for workflow run %s", workflow_run_id)
