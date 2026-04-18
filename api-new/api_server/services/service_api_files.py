"""FastAPI-native file helpers for the `/v1` service API slice."""

from __future__ import annotations

from sqlalchemy import select

from api_server.errors import forbidden, not_found
from api_server.models.app import App, EndUser, Message, MessageFile, UploadFile
from api_server.services.file_access import FileAccessService
from api_server.services.file_upload import FileUploadService, UploadedFileResponseDict
from extensions.ext_database import db


class ServiceApiFileService:
    """Handle file upload and app-scoped file preview checks for service API routes."""

    @staticmethod
    async def upload_file(
        *,
        app: App,
        user: EndUser,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> UploadedFileResponseDict:
        _ = app
        return await FileUploadService.upload_file(
            filename=filename,
            content=content,
            mimetype=mime_type,
            user=user,
        )

    @staticmethod
    async def get_owned_upload_file(*, app: App, file_id: str) -> UploadFile:
        async with db.session_context() as session:
            message_file = await session.scalar(
                select(MessageFile).where(MessageFile.upload_file_id == file_id).limit(1)
            )
            if message_file is None:
                raise not_found("file_not_found", "The requested file was not found.")

            message = await session.scalar(
                select(Message).where(
                    Message.id == message_file.message_id,
                    Message.app_id == app.id,
                )
            )
            if message is None:
                raise forbidden("file_access_denied", "Access to the requested file is denied.")

            upload_file = await session.scalar(select(UploadFile).where(UploadFile.id == file_id).limit(1))
            if upload_file is None:
                raise not_found("file_not_found", "The requested file was not found.")
            if upload_file.tenant_id != app.tenant_id:
                raise forbidden("file_access_denied", "Access to the requested file is denied.")

        return upload_file

    @staticmethod
    def get_file_path(upload_file: UploadFile):
        return FileAccessService.get_file_path(upload_file)
