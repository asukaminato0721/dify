from __future__ import annotations

from api_server.models.workflow import WorkflowAppLog, WorkflowAppLogCreatedFrom
from models.enums import CreatorUserRole


def test_workflow_app_log_provides_id_and_enum_for_active_write_path() -> None:
    workflow_app_log = WorkflowAppLog(
        tenant_id="tenant-1",
        app_id="app-1",
        workflow_id="workflow-1",
        workflow_run_id="run-1",
        created_from=WorkflowAppLogCreatedFrom.WEB_APP,
        created_by_role=CreatorUserRole.END_USER,
        created_by="end-user-1",
    )

    assert workflow_app_log.id
    assert workflow_app_log.created_from is WorkflowAppLogCreatedFrom.WEB_APP
