"""Retention CLI commands for the FastAPI port."""

from __future__ import annotations

from commands._common import unsupported_with_options

archive_workflow_runs = unsupported_with_options("archive-workflow-runs")
clean_expired_messages = unsupported_with_options("clean-expired-messages")
clean_workflow_runs = unsupported_with_options("clean-workflow-runs")
cleanup_orphaned_draft_variables = unsupported_with_options("cleanup-orphaned-draft-variables")
clear_free_plan_tenant_expired_logs = unsupported_with_options("clear-free-plan-tenant-expired-logs")
delete_archived_workflow_runs = unsupported_with_options("delete-archived-workflow-runs")
export_app_messages = unsupported_with_options("export-app-messages")
restore_workflow_runs = unsupported_with_options("restore-workflow-runs")
