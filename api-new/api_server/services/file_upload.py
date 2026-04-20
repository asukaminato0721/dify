from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path
from typing import Literal, TypedDict

from api_server.errors import bad_request, forbidden
from api_server.models.app import CreatorUserRole, EndUser, StorageType, UploadFile
from configs import dify_config
from constants import AUDIO_EXTENSIONS, DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from extensions.ext_database import db


class UploadedFileResponseDict(TypedDict):
    id: str
    name: str
    size: int
    extension: str | None
    mime_type: str | None
    created_by: str | None
    created_at: int | None
    url: str


class FileUploadService:
    """Local filesystem-backed upload service for the FastAPI port.

    Filesystem writes are dispatched to a worker thread so the async upload
    handlers do not block the event loop while preserving the same storage
    layout and validation behavior.
    """

    @staticmethod
    def _persist_upload_file(*, file_path: Path, content: bytes) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

    @staticmethod
    async def upload_file(
        *,
        filename: str,
        content: bytes,
        mimetype: str,
        user: EndUser,
        source: Literal["datasets"] | None = None,
        source_url: str = "",
    ) -> UploadedFileResponseDict:
        extension = os.path.splitext(filename)[1].lstrip(".").lower()
        if not filename:
            raise bad_request("filename_missing", "Filename is required.")
        if any(char in filename for char in ["/", "\\"]):
            raise bad_request("invalid_filename", "Filename contains invalid characters.")
        if source == "datasets" and extension not in DOCUMENT_EXTENSIONS:
            raise forbidden("unsupported_file_type", "Unsupported file type.")

        file_size = len(content)
        if not FileUploadService.is_file_size_within_limit(extension=extension, file_size=file_size):
            raise forbidden("file_too_large", "File is too large.")

        storage_root = Path(dify_config.STORAGE_LOCAL_PATH)
        file_id = str(uuid.uuid4())
        file_key = f"upload_files/{user.tenant_id}/{file_id}.{extension}"
        file_path = storage_root / file_key
        await asyncio.to_thread(
            FileUploadService._persist_upload_file,
            file_path=file_path,
            content=content,
        )

        upload_file = UploadFile(
            id=file_id,
            tenant_id=user.tenant_id,
            storage_type=StorageType.LOCAL.value,
            key=file_key,
            name=filename,
            size=file_size,
            extension=extension,
            mime_type=mimetype,
            created_by_role=CreatorUserRole.END_USER.value,
            created_by=user.id,
            used=False,
            hash=hashlib.sha3_256(content).hexdigest(),
            source_url=source_url,
        )

        async with db.session_context() as session:
            async with session.begin():
                session.add(upload_file)

        created_at = int(upload_file.created_at.timestamp()) if upload_file.created_at else None
        return {
            "id": upload_file.id,
            "name": upload_file.name,
            "size": upload_file.size,
            "extension": upload_file.extension,
            "mime_type": upload_file.mime_type,
            "created_by": upload_file.created_by,
            "created_at": created_at,
            "url": f"/files/{upload_file.id}",
        }

    @staticmethod
    def is_file_size_within_limit(*, extension: str, file_size: int) -> bool:
        if extension in IMAGE_EXTENSIONS:
            file_size_limit = dify_config.UPLOAD_IMAGE_FILE_SIZE_LIMIT * 1024 * 1024
        elif extension in VIDEO_EXTENSIONS:
            file_size_limit = dify_config.UPLOAD_VIDEO_FILE_SIZE_LIMIT * 1024 * 1024
        elif extension in AUDIO_EXTENSIONS:
            file_size_limit = dify_config.UPLOAD_AUDIO_FILE_SIZE_LIMIT * 1024 * 1024
        else:
            file_size_limit = dify_config.UPLOAD_FILE_SIZE_LIMIT * 1024 * 1024
        return file_size <= file_size_limit
