from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from api_server.errors import ApiError
from api_server.middleware import RequestContextMiddleware
from api_server.routes.audio import router as audio_router
from api_server.routes.bootstrap import router as bootstrap_router
from api_server.routes.conversation import router as conversation_router
from api_server.routes.console_misc import router as console_misc_router
from api_server.routes.files import router as files_router
from api_server.routes.generation import router as generation_router
from api_server.routes.health import router as health_router
from api_server.routes.human_input_form import router as human_input_form_router
from api_server.routes.mcp import router as mcp_router
from api_server.routes.inner_api import router as inner_api_router
from api_server.routes.inner_api_plugin import router as inner_api_plugin_router
from api_server.routes.service_api import router as service_api_router
from api_server.routes.task_control import router as task_control_router
from api_server.routes.trigger import router as trigger_router
from api_server.routes.webapp import router as webapp_router
from api_server.routes.workflow_events import router as workflow_events_router
from configs import dify_config
from dify_app import DifyApp
from extensions import ext_celery, ext_redis, ext_storage
from extensions.ext_database import db

logger = logging.getLogger(__name__)


def _init_optional_extension(name: str, init: Callable[[], None]) -> None:
    try:
        init()
    except ModuleNotFoundError:
        logger.warning("Skipping optional extension initialization: %s", name, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_app(app)
    try:
        yield
    finally:
        await db.dispose()


def create_app() -> DifyApp:
    app = DifyApp(
        title="Dify API",
        version=dify_config.project.version,
        lifespan=lifespan,
    )
    db.init_app(app)
    ext_redis.init_app(app)
    _init_optional_extension("storage", lambda: ext_storage.init_app(app))
    ext_celery.init_app(app)
    app.add_middleware(
        SessionMiddleware,
        secret_key=dify_config.SECRET_KEY,
        same_site="lax",
        https_only=False,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(bootstrap_router)
    app.include_router(console_misc_router)
    app.include_router(audio_router)
    app.include_router(conversation_router)
    app.include_router(files_router)
    app.include_router(generation_router)
    app.include_router(task_control_router)
    app.include_router(human_input_form_router)
    app.include_router(mcp_router)
    app.include_router(inner_api_router)
    app.include_router(inner_api_plugin_router)
    app.include_router(service_api_router)
    app.include_router(trigger_router)
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
