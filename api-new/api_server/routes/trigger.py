from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Iterator, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from werkzeug.exceptions import RequestEntityTooLarge

from core.plugin.utils.http_parser import deserialize_request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trigger"])

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
UUID_MATCHER = re.compile(UUID_PATTERN)


async def _build_flask_request(request: Request):
    body = await request.body()
    query = request.url.query
    path = request.url.path if not query else f"{request.url.path}?{query}"
    raw = f"{request.method} {path} HTTP/1.1\r\n".encode()
    for name, value in request.headers.items():
        raw += f"{name}: {value}\r\n".encode()
    raw += b"\r\n"
    raw += body
    return deserialize_request(raw)


def _get_trigger_services():
    from services.trigger.trigger_service import TriggerService
    from services.trigger.trigger_subscription_builder_service import TriggerSubscriptionBuilderService

    return TriggerService, TriggerSubscriptionBuilderService


def _get_webhook_service():
    from services.trigger.webhook_service import WebhookService

    return WebhookService


def _get_trigger_debug_helpers():
    from core.trigger.debug.event_bus import TriggerDebugEventBus
    from core.trigger.debug.events import WebhookDebugEvent, build_webhook_pool_key

    return TriggerDebugEventBus, WebhookDebugEvent, build_webhook_pool_key


def _from_flask_response(response) -> Response:
    fastapi_response = Response(
        content=response.get_data(),
        status_code=response.status_code,
        media_type=response.mimetype or "application/json",
    )
    for name, value in response.headers.items():
        fastapi_response.headers[name] = value
    return fastapi_response


@contextmanager
def _patched_webhook_request(flask_request) -> Iterator[None]:
    import services.trigger.webhook_service as webhook_service_module

    original_request = webhook_service_module.request
    webhook_service_module.request = flask_request
    try:
        yield
    finally:
        webhook_service_module.request = original_request


def _prepare_webhook_execution(flask_request, webhook_id: str, *, is_debug: bool = False):
    WebhookService = _get_webhook_service()

    with _patched_webhook_request(flask_request):
        webhook_trigger, workflow, node_config = WebhookService.get_webhook_trigger_and_workflow(
            webhook_id, is_debug=is_debug
        )
        webhook_data: dict[str, Any]
        try:
            webhook_data = cast(
                dict[str, Any],
                WebhookService.extract_and_validate_webhook_data(webhook_trigger, node_config),
            )
            return webhook_trigger, workflow, node_config, webhook_data, None
        except ValueError as exc:
            webhook_data = {
                "method": flask_request.method,
                "headers": dict(flask_request.headers),
                "query_params": dict(flask_request.args),
                "body": {},
                "files": {},
            }
            return webhook_trigger, workflow, node_config, webhook_data, str(exc)


@router.api_route("/triggers/plugin/{endpoint_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def trigger_endpoint(request: Request, endpoint_id: str) -> Response:
    if not UUID_MATCHER.match(endpoint_id):
        return JSONResponse(status_code=404, content={"error": "Invalid endpoint ID"})

    flask_request = await _build_flask_request(request)
    TriggerService, TriggerSubscriptionBuilderService = _get_trigger_services()

    handling_chain = [
        TriggerService.process_endpoint,
        TriggerSubscriptionBuilderService.process_builder_validation_endpoint,
    ]

    try:
        for handler in handling_chain:
            response = await asyncio.to_thread(handler, endpoint_id, flask_request)
            if response:
                return _from_flask_response(response)
        logger.info("Endpoint not found for %s", endpoint_id)
        return JSONResponse(status_code=404, content={"error": "Endpoint not found"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": "Endpoint processing failed", "message": str(exc)})
    except Exception:
        logger.exception("Trigger endpoint processing failed for %s", endpoint_id)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


@router.api_route("/triggers/webhook/{webhook_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def handle_webhook(request: Request, webhook_id: str) -> Response:
    flask_request = await _build_flask_request(request)
    WebhookService = _get_webhook_service()

    try:
        webhook_trigger, workflow, node_config, webhook_data, error = await asyncio.to_thread(
            _prepare_webhook_execution,
            flask_request,
            webhook_id,
            is_debug=False,
        )
        if error:
            return JSONResponse(status_code=400, content={"error": "Bad Request", "message": error})

        await asyncio.to_thread(
            WebhookService.trigger_workflow_execution,
            webhook_trigger,
            cast(Any, webhook_data),
            workflow,
        )
        response_data, status_code = await asyncio.to_thread(
            WebhookService.generate_webhook_response,
            node_config,
        )
        return JSONResponse(status_code=status_code, content=response_data)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except RequestEntityTooLarge:
        raise
    except Exception as exc:
        logger.exception("Webhook processing failed for %s", webhook_id)
        return JSONResponse(status_code=500, content={"error": "Internal server error", "message": str(exc)})


@router.api_route("/triggers/webhook-debug/{webhook_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def handle_webhook_debug(request: Request, webhook_id: str) -> Response:
    flask_request = await _build_flask_request(request)
    TriggerDebugEventBus, WebhookDebugEvent, build_webhook_pool_key = _get_trigger_debug_helpers()
    WebhookService = _get_webhook_service()

    try:
        webhook_trigger, _, node_config, webhook_data, error = await asyncio.to_thread(
            _prepare_webhook_execution,
            flask_request,
            webhook_id,
            is_debug=True,
        )
        if error:
            return JSONResponse(status_code=400, content={"error": "Bad Request", "message": error})

        workflow_inputs = await asyncio.to_thread(WebhookService.build_workflow_inputs, cast(Any, webhook_data))
        pool_key = build_webhook_pool_key(
            tenant_id=webhook_trigger.tenant_id,
            app_id=webhook_trigger.app_id,
            node_id=webhook_trigger.node_id,
        )
        event = WebhookDebugEvent(
            request_id=f"webhook_debug_{webhook_trigger.webhook_id}",
            timestamp=int(time.time()),
            node_id=webhook_trigger.node_id,
            payload={
                "inputs": workflow_inputs,
                "webhook_data": webhook_data,
                "method": webhook_data.get("method"),
            },
        )
        dispatch_count = TriggerDebugEventBus.dispatch(
            tenant_id=webhook_trigger.tenant_id,
            event=event,
            pool_key=pool_key,
        )
        if dispatch_count == 0:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "No active debug listener",
                    "message": "The webhook debug URL only works while the Variable Inspector is listening. Use the published webhook URL to execute the workflow in Celery.",
                    "execution_url": webhook_trigger.webhook_url,
                },
            )

        response_data, status_code = await asyncio.to_thread(
            WebhookService.generate_webhook_response,
            node_config,
        )
        return JSONResponse(status_code=status_code, content=response_data)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except RequestEntityTooLarge:
        raise
    except Exception:
        logger.exception("Webhook debug processing failed for %s", webhook_id)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "message": "An internal error has occurred."},
        )
