"""Plugin CLI commands for the FastAPI port."""

from __future__ import annotations

from commands._common import unsupported_with_options

extract_plugins = unsupported_with_options("extract-plugins")
extract_unique_plugins = unsupported_with_options("extract-unique-plugins")
install_plugins = unsupported_with_options("install-plugins")
install_rag_pipeline_plugins = unsupported_with_options("install-rag-pipeline-plugins")
migrate_data_for_plugin = unsupported_with_options("migrate-data-for-plugin")
setup_datasource_oauth_client = unsupported_with_options("setup-datasource-oauth-client")
setup_system_tool_oauth_client = unsupported_with_options("setup-system-tool-oauth-client")
setup_system_trigger_oauth_client = unsupported_with_options("setup-system-trigger-oauth-client")
transform_datasource_credentials = unsupported_with_options("transform-datasource-credentials")
