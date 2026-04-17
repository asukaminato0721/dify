from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from opentelemetry.trace import get_current_span
from opentelemetry.trace.span import INVALID_SPAN_ID, INVALID_TRACE_ID
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request identifier and propagate tracing metadata to responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers.setdefault("X-Request-Id", request_id)

        span = get_current_span()
        context = span.get_span_context() if span else None
        if context and context.is_valid:
            if context.trace_id != INVALID_TRACE_ID:
                response.headers.setdefault("X-Trace-Id", format(context.trace_id, "032x"))
            if context.span_id != INVALID_SPAN_ID:
                response.headers.setdefault("X-Span-Id", format(context.span_id, "016x"))

        return response
