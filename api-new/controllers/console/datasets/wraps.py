from collections.abc import Callable
from functools import wraps

from flask import current_app
from sqlalchemy import select

from controllers.console.datasets.error import PipelineNotFoundError
from extensions.ext_database import db
from libs.login import current_account_with_tenant
from models.dataset import Pipeline


def get_rag_pipeline[**P, R](view_func: Callable[P, R]) -> Callable[P, R]:
    @wraps(view_func)
    def decorated_view(*args: P.args, **kwargs: P.kwargs) -> R:
        if not kwargs.get("pipeline_id"):
            raise ValueError("missing pipeline_id in path parameters")

        _, current_tenant_id = current_account_with_tenant()

        pipeline_id = kwargs.get("pipeline_id")
        pipeline_id = str(pipeline_id)

        del kwargs["pipeline_id"]

        pipeline = current_app.ensure_sync(_load_pipeline)(pipeline_id, current_tenant_id)

        if not pipeline:
            raise PipelineNotFoundError()

        kwargs["pipeline"] = pipeline

        return view_func(*args, **kwargs)

    return decorated_view


async def _load_pipeline(pipeline_id: str, tenant_id: str) -> Pipeline | None:
    async with db.session_context() as session:
        return await session.scalar(
            select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.tenant_id == tenant_id).limit(1)
        )
