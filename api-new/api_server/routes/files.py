from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from api_server.errors import forbidden
from api_server.services.file_access import FileAccessService

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
