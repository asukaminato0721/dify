from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from api_server.errors import ApiError
from api_server.middleware import RequestContextMiddleware
from api_server.routes.audio import router as audio_router
from api_server.routes.bootstrap import router as bootstrap_router
from api_server.routes.conversation import router as conversation_router
from api_server.routes.files import router as files_router
from api_server.routes.generation import router as generation_router
from api_server.routes.health import router as health_router
from api_server.routes.human_input_form import router as human_input_form_router
from api_server.routes.task_control import router as task_control_router
from api_server.routes.webapp import router as webapp_router
from api_server.routes.workflow_events import router as workflow_events_router
from configs import dify_config
from dify_app import DifyApp
from extensions import ext_redis
from extensions.ext_database import db

logger = logging.getLogger(__name__)


class _RedisExtensionAdapter:
    """Expose the legacy `extensions` slot expected by the Redis bootstrap."""

    extensions: dict[str, object]

    def __init__(self, app: FastAPI) -> None:
        state_extensions = getattr(app.state, "extensions", None)
        if isinstance(state_extensions, dict):
            self.extensions = state_extensions
        else:
            self.extensions = {}
            app.state.extensions = self.extensions


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_app(app)
    ext_redis.init_app(cast(DifyApp, _RedisExtensionAdapter(app)))
    try:
        yield
    finally:
        await db.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dify API",
        version=dify_config.project.version,
        lifespan=lifespan,
    )
    db.init_app(app)
    app.add_middleware(
        SessionMiddleware,
        secret_key=dify_config.SECRET_KEY,
        same_site="lax",
        https_only=False,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(bootstrap_router)
    app.include_router(audio_router)
    app.include_router(conversation_router)
    app.include_router(files_router)
    app.include_router(generation_router)
    app.include_router(task_control_router)
    app.include_router(human_input_form_router)
    app.include_router(webapp_router)
    app.include_router(workflow_events_router)

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return JSONResponse(status_code=500, content={"code": "internal_server_error", "message": str(exc)})

    return app
