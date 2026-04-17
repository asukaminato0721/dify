from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from api_server.errors import ApiError
from api_server.routes.conversation import router as conversation_router
from api_server.middleware import RequestContextMiddleware
from api_server.routes.bootstrap import router as bootstrap_router
from api_server.routes.health import router as health_router
from api_server.routes.task_control import router as task_control_router
from api_server.routes.webapp import router as webapp_router
from configs import dify_config
from extensions.ext_database import db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_app(app)
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
    app.add_middleware(
        SessionMiddleware,
        secret_key=dify_config.SECRET_KEY,
        same_site="lax",
        https_only=False,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(bootstrap_router)
    app.include_router(conversation_router)
    app.include_router(task_control_router)
    app.include_router(webapp_router)

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
