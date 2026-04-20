from __future__ import annotations

import asyncio
from mimetypes import guess_extension
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File as FastAPIFile, Query, UploadFile as FastAPIUploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from api_server.errors import ApiError, bad_request, forbidden, not_found
from api_server.models.app import DefaultEndUserSessionID, EndUser
from api_server.services.file_access import FileAccessService
from core.tools.signature import verify_plugin_file_signature, verify_tool_file_signature
from core.tools.tool_file_manager import ToolFileManager
from services.errors.file import FileTooLargeError as FileTooLargeServiceError
from services.errors.file import UnsupportedFileTypeError as UnsupportedFileTypeServiceError
from extensions.ext_database import db

router = APIRouter(tags=["files"])

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "svg"}
HTML_EXTENSIONS = {"html", "htm"}


def _build_file_response(path: Path, *, filename: str, media_type: str | None, as_attachment: bool) -> FileResponse:
    response = FileResponse(path=path, media_type=media_type or "application/octet-stream", filename=filename)
    if media_type in {
        "audio/mpeg",
        "audio/wav",
        "audio/mp4",
        "audio/ogg",
        "audio/flac",
        "audio/aac",
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "audio/x-m4a",
    }:
        response.headers["Accept-Ranges"] = "bytes"
    if as_attachment:
        encoded_filename = quote(filename)
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in HTML_EXTENSIONS:
        if as_attachment:
            response.headers["Content-Type"] = "application/octet-stream"
            response.headers["X-Content-Type-Options"] = "nosniff"
        else:
            raise forbidden("unsupported_file_type", "HTML previews must be downloaded as attachments.")
    return response


def _unsupported_file_type() -> ApiError:
    return ApiError(status_code=415, code="unsupported_file_type", message="File type not allowed.")


async def _get_or_create_plugin_user(tenant_id: str, user_id: str | None) -> EndUser:
    resolved_user_id = user_id or DefaultEndUserSessionID.DEFAULT_SESSION_ID
    is_anonymous = resolved_user_id == DefaultEndUserSessionID.DEFAULT_SESSION_ID

    async with db.session_context() as session:
        if is_anonymous:
            stmt = select(EndUser).where(
                EndUser.session_id == resolved_user_id,
                EndUser.tenant_id == tenant_id,
            ).limit(1)
        else:
            stmt = select(EndUser).where(
                EndUser.id == resolved_user_id,
                EndUser.tenant_id == tenant_id,
            ).limit(1)

        user_model = await session.scalar(stmt)
        if user_model is None:
            user_model = EndUser(
                tenant_id=tenant_id,
                type="service_api",
                is_anonymous=is_anonymous,
                session_id=resolved_user_id,
            )
            session.add(user_model)
            await session.flush()
            await session.refresh(user_model)
            await session.commit()

        return user_model


@router.get("/files/{file_id}/image-preview")
async def get_image_preview(file_id: str) -> FileResponse:
    upload_file = await FileAccessService.get_upload_file(file_id)
    if upload_file.extension.lower() not in IMAGE_EXTENSIONS:
        raise forbidden("unsupported_file_type", "Unsupported file type.")
    path = FileAccessService.get_file_path(upload_file)
    return _build_file_response(path, filename=upload_file.name, media_type=upload_file.mime_type, as_attachment=False)


@router.get("/files/{file_id}/file-preview")
async def get_file_preview(
    file_id: str,
    as_attachment: bool = Query(default=False),
) -> FileResponse:
    upload_file = await FileAccessService.get_upload_file(file_id)
    path = FileAccessService.get_file_path(upload_file)
    return _build_file_response(
        path,
        filename=upload_file.name,
        media_type=upload_file.mime_type,
        as_attachment=as_attachment,
    )


@router.get("/files/workspaces/{workspace_id}/webapp-logo")
async def get_workspace_webapp_logo(workspace_id: str) -> FileResponse:
    file_id = await FileAccessService.get_workspace_logo_file_id(workspace_id)
    upload_file = await FileAccessService.get_upload_file(file_id)
    if upload_file.extension.lower() not in IMAGE_EXTENSIONS:
        raise forbidden("unsupported_file_type", "Unsupported file type.")
    path = FileAccessService.get_file_path(upload_file)
    return _build_file_response(path, filename=upload_file.name, media_type=upload_file.mime_type, as_attachment=False)


@router.get("/files/tools/{file_id}.{extension}")
async def get_tool_file(
    file_id: str,
    extension: str,
    timestamp: str,
    nonce: str,
    sign: str,
    as_attachment: bool = Query(default=False),
) -> StreamingResponse:
    if not verify_tool_file_signature(file_id=file_id, timestamp=timestamp, nonce=nonce, sign=sign):
        raise forbidden("invalid_request", "Invalid request.")

    try:
        stream, tool_file = await asyncio.to_thread(ToolFileManager().get_file_generator_by_tool_file_id, file_id)
    except Exception as exc:  # pragma: no cover - defensive parity with Flask path
        raise _unsupported_file_type() from exc

    if stream is None or tool_file is None:
        raise not_found("not_found", "file is not found")

    filename = tool_file.filename or f"{file_id}.{extension}"
    media_type = tool_file.mime_type or "application/octet-stream"
    response = StreamingResponse(stream, media_type=media_type)
    if tool_file.size > 0:
        response.headers["Content-Length"] = str(tool_file.size)

    html_content = (extension or "").lower() in HTML_EXTENSIONS or media_type in {
        "text/html",
        "application/xhtml+xml",
    }
    if as_attachment or html_content:
        encoded_filename = quote(filename)
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
    if html_content:
        response.headers["Content-Type"] = "application/octet-stream"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.post("/files/upload/for-plugin", status_code=201)
async def upload_file_for_plugin(
    timestamp: str,
    nonce: str,
    sign: str,
    tenant_id: str,
    user_id: str | None = None,
    file: FastAPIUploadFile = FastAPIFile(...),
) -> dict[str, str | int | None]:
    if not file.filename or not file.content_type:
        raise forbidden("invalid_request", "Invalid request.")

    user = await _get_or_create_plugin_user(tenant_id=tenant_id, user_id=user_id)
    if not verify_plugin_file_signature(
        filename=file.filename,
        mimetype=file.content_type,
        tenant_id=tenant_id,
        user_id=user.id,
        timestamp=timestamp,
        nonce=nonce,
        sign=sign,
    ):
        raise forbidden("invalid_request", "Invalid request.")

    try:
        tool_file = await asyncio.to_thread(
            ToolFileManager().create_file_by_raw,
            user_id=user.id,
            tenant_id=tenant_id,
            file_binary=await file.read(),
            mimetype=file.content_type,
            filename=file.filename,
            conversation_id=None,
        )
    except FileTooLargeServiceError as exc:
        raise ApiError(status_code=413, code="file_too_large", message=exc.description or "File too large.") from exc
    except UnsupportedFileTypeServiceError as exc:
        raise _unsupported_file_type() from exc

    extension = guess_extension(tool_file.mimetype) or ".bin"
    preview_url = ToolFileManager.sign_file(tool_file_id=tool_file.id, extension=extension)
    return {
        "id": tool_file.id,
        "name": tool_file.name,
        "size": tool_file.size,
        "extension": extension,
        "mime_type": tool_file.mimetype,
        "preview_url": preview_url,
        "source_url": tool_file.original_url,
        "original_url": tool_file.original_url,
        "user_id": tool_file.user_id,
        "tenant_id": tool_file.tenant_id,
        "conversation_id": tool_file.conversation_id,
        "file_key": tool_file.file_key,
        "created_by": None,
        "created_at": None,
    }
