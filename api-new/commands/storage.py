"""Storage CLI commands for the FastAPI port."""

from __future__ import annotations

from commands._common import unsupported_with_options

clear_orphaned_file_records = unsupported_with_options("clear-orphaned-file-records")
file_usage = unsupported_with_options("file-usage")
migrate_oss = unsupported_with_options("migrate-oss")
remove_orphaned_files_on_storage = unsupported_with_options("remove-orphaned-files-on-storage")
