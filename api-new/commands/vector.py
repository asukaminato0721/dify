"""Vector CLI commands for the FastAPI port."""

from __future__ import annotations

from commands._common import unsupported_with_options

add_qdrant_index = unsupported_with_options("add-qdrant-index")
migrate_annotation_vector_database = unsupported_with_options("migrate-annotation-vector-database")
migrate_knowledge_vector_database = unsupported_with_options("migrate-knowledge-vector-database")
old_metadata_migration = unsupported_with_options("old-metadata-migration")
vdb_migrate = unsupported_with_options("vdb-migrate")
