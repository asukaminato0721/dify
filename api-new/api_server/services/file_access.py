from __future__ import annotations

from pathlib import Path

from api_server.errors import bad_request
from api_server.models.app import Tenant, UploadFile
from configs import dify_config
from extensions.ext_database import db
from sqlalchemy import select


class FileAccessService:
    """Local filesystem-backed file access helpers for FastAPI file routes."""

    @staticmethod
    def _storage_root() -> Path:
        root = Path(dify_config.STORAGE_LOCAL_PATH)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    async def get_upload_file(file_id: str) -> UploadFile:
        async with db.session_context() as session:
            upload_file = await session.scalar(select(UploadFile).where(UploadFile.id == file_id).limit(1))
        if upload_file is None:
            raise bad_request("file_not_found", "File not found")
        return upload_file

    @staticmethod
    def get_file_path(upload_file: UploadFile) -> Path:
        path = FileAccessService._storage_root() / upload_file.key
        if not path.exists():
            raise bad_request("file_not_found", "File not found")
        return path

    @staticmethod
    async def get_workspace_logo_file_id(workspace_id: str) -> str:
        async with db.session_context() as session:
            tenant = await session.scalar(select(Tenant).where(Tenant.id == workspace_id).limit(1))
        if tenant is None:
            raise bad_request("file_not_found", "webapp logo is not found")
        logo_id = tenant.custom_config_dict.get("replace_webapp_logo")
        if not isinstance(logo_id, str) or not logo_id:
            raise bad_request("file_not_found", "webapp logo is not found")
        return logo_id
