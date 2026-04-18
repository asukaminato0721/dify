from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from api_server.models.app import EndUser
from core.app.apps.workflow.generate_task_pipeline import WorkflowAppGenerateTaskPipeline
from core.app.entities.app_invoke_entities import InvokeFrom
from libs.helper import extract_tenant_id
from models.enums import CreatorUserRole


def _build_local_end_user() -> EndUser:
    return EndUser(
        id="end-user-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type="session",
        external_user_id=None,
        name="Ada",
        is_anonymous=False,
        session_id="session-1",
    )


def test_extract_tenant_id_accepts_local_end_user() -> None:
    assert extract_tenant_id(_build_local_end_user()) == "tenant-1"


def test_workflow_pipeline_treats_local_end_user_as_end_user() -> None:
    end_user = _build_local_end_user()
    pipeline = WorkflowAppGenerateTaskPipeline(
        application_generate_entity=cast(
            Any,
            SimpleNamespace(
                task_id="task-1",
                app_config=SimpleNamespace(
                    app_id="app-1",
                    tenant_id="tenant-1",
                    sensitive_word_avoidance=None,
                ),
                files=[],
                workflow_execution_id="run-1",
                inputs={},
                invoke_from=InvokeFrom.WEB_APP,
            ),
        ),
        workflow=cast(Any, SimpleNamespace(id="workflow-1", features_dict={})),
        queue_manager=cast(Any, SimpleNamespace(invoke_from=InvokeFrom.WEB_APP, graph_runtime_state=None)),
        user=end_user,
        stream=False,
        draft_var_saver_factory=cast(Any, lambda *args, **kwargs: None),
    )

    assert pipeline._created_by_role == CreatorUserRole.END_USER
    assert pipeline._user_id == end_user.id
