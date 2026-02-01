import re
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, Flask, current_app, got_request_exception
from werkzeug.exceptions import HTTPException
from werkzeug.http import HTTP_STATUS_CODES

from configs import dify_config
from core.errors.error import AppInvokeQuotaExceededError
from libs.openapi import Namespace, register_resource
from libs.token import build_force_logout_cookie_headers


def http_status_message(code: int) -> str:
    return HTTP_STATUS_CODES.get(code, "")


def register_external_error_handlers(target: Blueprint | Flask, *, default_mediatype: str | None = None) -> None:
    def handle_http_exception(e: HTTPException):
        got_request_exception.send(current_app, exception=e)

        # If Werkzeug already prepared a Response, just use it.
        if e.response is not None:
            return e.response

        status_code = getattr(e, "code", 500) or 500

        # Build a safe, dict-like payload
        default_data = {
            "code": re.sub(r"(?<!^)(?=[A-Z])", "_", type(e).__name__).lower(),
            "message": getattr(e, "description", http_status_message(status_code)),
            "status": status_code,
        }
        if default_data["message"] == "Failed to decode JSON object: Expecting value: line 1 column 1 (char 0)":
            default_data["message"] = "Invalid JSON payload received or JSON payload is empty."

        # Use headers on the exception if present; otherwise none.
        headers: dict[str, Any] = {}
        exc_headers = getattr(e, "headers", None)
        if exc_headers:
            headers.update(exc_headers)

        # Payload per status
        if status_code == 406 and default_mediatype is None:
            data = {"code": "not_acceptable", "message": default_data["message"], "status": status_code}
            return data, status_code, headers
        if status_code == 400:
            msg = default_data["message"]
            if isinstance(msg, Mapping) and msg:
                # Convert param errors like {"field": "reason"} into a friendly shape
                param_key, param_value = next(iter(msg.items()))
                data = {
                    "code": "invalid_param",
                    "message": str(param_value),
                    "params": param_key,
                    "status": status_code,
                }
            else:
                data = {**default_data}
                data.setdefault("code", "unknown")
            return data, status_code, headers

        data = {**default_data}
        data.setdefault("code", "unknown")
        # If you need WWW-Authenticate for 401, add it to headers
        if status_code == 401:
            headers["WWW-Authenticate"] = 'Bearer realm="api"'
            # Check if this is a forced logout error - clear cookies
            error_code = getattr(e, "error_code", None)
            if error_code == "unauthorized_and_force_logout":
                # Add Set-Cookie headers to clear auth cookies
                headers["Set-Cookie"] = build_force_logout_cookie_headers()
        return data, status_code, headers

    target.register_error_handler(HTTPException, handle_http_exception)

    def handle_value_error(e: ValueError):
        got_request_exception.send(current_app, exception=e)
        status_code = 400
        data = {"code": "invalid_param", "message": str(e), "status": status_code}
        return data, status_code

    target.register_error_handler(ValueError, handle_value_error)

    def handle_quota_exceeded(e: AppInvokeQuotaExceededError):
        got_request_exception.send(current_app, exception=e)
        status_code = 429
        data = {"code": "too_many_requests", "message": str(e), "status": status_code}
        return data, status_code

    target.register_error_handler(AppInvokeQuotaExceededError, handle_quota_exceeded)

    def handle_general_exception(e: Exception):
        got_request_exception.send(current_app, exception=e)

        status_code = 500
        data: dict[str, Any] = getattr(e, "data", {"message": http_status_message(status_code)})

        # Normalize non-mapping data (e.g., if someone set e.data = Response)
        if not isinstance(data, dict):
            data = {"message": str(e)}

        data.setdefault("code", "unknown")
        data.setdefault("status", status_code)

        # Note: Exception logging is handled by Flask framework automatically
        return data, status_code

    target.register_error_handler(Exception, handle_general_exception)


class ExternalApi:
    _authorizations = {
        "Bearer": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Type: Bearer {your-api-key}",
        }
    }

    def __init__(self, app: Blueprint | Flask, *args: Any, **kwargs: Any) -> None:
        _ = args
        _ = kwargs
        self.app = app
        self.default_mediatype: str | None = None
        self.specs_enabled = dify_config.SWAGGER_UI_ENABLED
        self.doc_path = dify_config.SWAGGER_UI_PATH if dify_config.SWAGGER_UI_ENABLED else None
        register_external_error_handlers(self.app, default_mediatype=self.default_mediatype)

    def add_namespace(self, namespace: Namespace) -> None:
        namespace.register(self.app)

    def add_resource(self, resource_cls: type, path: str, **options: Any) -> None:
        register_resource(self.app, path, resource_cls, **options)

    def route(self, path: str, **options: Any):
        def decorator(resource_cls: type):
            self.add_resource(resource_cls, path, **options)
            return resource_cls

        return decorator
