from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, File as FastAPIFile, Form, Query, Request, UploadFile as FastAPIUploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

import services
from api_server.errors import ApiError, forbidden
from api_server.routes.console_misc import _ensure_console_setup, _resolve_console_account
from configs import dify_config
from constants import DOCUMENT_EXTENSIONS
from controllers.common.helpers import guess_file_info_from_response
from core.db.session_factory import get_sync_session_maker
from core.helper import ssrf_proxy
from graphon.file import helpers as file_helpers
from services.billing_service import BillingService
from services.feature_service import FeatureService
from services.file_service import FileService

router = APIRouter(tags=["console"])

_FALLBACK_LANG = "en-US"


def _sync_session_maker() -> sessionmaker[Session]:
    return cast(sessionmaker[Session], get_sync_session_maker())


class DismissNotificationPayload(BaseModel):
    notification_id: str = Field(...)


class RemoteFileUploadPayload(BaseModel):
    url: str = Field(...)


def _ensure_cloud() -> None:
    if dify_config.EDITION != "CLOUD":
        raise ApiError(status_code=404, code="not_found", message="Not found.")


def _pick_lang_content(contents: dict[str, dict[str, Any]], lang: str) -> dict[str, Any]:
    return contents.get(lang) or contents.get(_FALLBACK_LANG) or next(iter(contents.values()), {})


@router.get("/console/api/notification")
async def get_console_notification(request: Request) -> dict[str, Any]:
    await _ensure_console_setup()
    _ensure_cloud()
    account = await _resolve_console_account(request)
    result = await asyncio.to_thread(BillingService.get_account_notification, str(account.id))
    if not result.get("shouldShow"):
        return {"should_show": False, "notifications": []}

    lang = account.interface_language or _FALLBACK_LANG
    notifications: list[dict[str, Any]] = []
    for notification in result.get("notifications") or []:
        contents = notification.get("contents") or {}
        lang_content = _pick_lang_content(contents, lang)
        notifications.append(
            {
                "notification_id": notification.get("notificationId"),
                "frequency": notification.get("frequency"),
                "lang": lang_content.get("lang", lang),
                "title": lang_content.get("title", ""),
                "subtitle": lang_content.get("subtitle", ""),
                "body": lang_content.get("body", ""),
                "title_pic_url": lang_content.get("titlePicUrl", ""),
            }
        )
    return {"should_show": bool(notifications), "notifications": notifications}


@router.post("/console/api/notification/dismiss")
async def dismiss_console_notification(request: Request, payload: DismissNotificationPayload) -> dict[str, str]:
    await _ensure_console_setup()
    _ensure_cloud()
    account = await _resolve_console_account(request)
    await asyncio.to_thread(BillingService.dismiss_notification, payload.notification_id, str(account.id))
    return {"result": "success"}


@router.get("/console/api/remote-files/{url:path}")
async def get_console_remote_file_info(request: Request, url: str) -> dict[str, Any]:
    await _ensure_console_setup()
    await _resolve_console_account(request)
    decoded_url = urllib.parse.unquote(url)
    resp = await asyncio.to_thread(ssrf_proxy.head, decoded_url)
    if resp.status_code != httpx.codes.OK:
        resp = await asyncio.to_thread(ssrf_proxy.get, decoded_url, timeout=3)
    resp.raise_for_status()
    return {
        "file_type": resp.headers.get("Content-Type", "application/octet-stream"),
        "file_length": int(resp.headers.get("Content-Length", 0)),
    }


@router.post("/console/api/remote-files/upload", status_code=201)
async def upload_console_remote_file(request: Request, payload: RemoteFileUploadPayload) -> dict[str, Any]:
    await _ensure_console_setup()
    account = await _resolve_console_account(request)

    try:
        resp = await asyncio.to_thread(ssrf_proxy.head, payload.url)
        if resp.status_code != httpx.codes.OK:
            resp = await asyncio.to_thread(ssrf_proxy.get, payload.url, timeout=3, follow_redirects=True)
        if resp.status_code != httpx.codes.OK:
            raise ApiError(status_code=400, code="remote_file_upload_error", message=f"Failed to fetch file from {payload.url}: {resp.text}")
    except httpx.RequestError as exc:
        raise ApiError(status_code=400, code="remote_file_upload_error", message=f"Failed to fetch file from {payload.url}: {str(exc)}") from exc

    file_info = guess_file_info_from_response(resp)
    if not FileService.is_file_size_within_limit(extension=file_info.extension, file_size=file_info.size):
        raise ApiError(status_code=413, code="file_too_large", message="File size exceeded.")

    content = resp.content if resp.request.method == "GET" else (await asyncio.to_thread(ssrf_proxy.get, payload.url)).content
    try:
        upload_file = await asyncio.to_thread(
            FileService(_sync_session_maker()).upload_file,
            filename=file_info.filename,
            content=content,
            mimetype=file_info.mimetype,
            user=account,
            source_url=payload.url,
        )
    except services.errors.file.FileTooLargeError as exc:
        raise ApiError(status_code=413, code="file_too_large", message=exc.description or "File size exceeded.") from exc
    except services.errors.file.UnsupportedFileTypeError as exc:
        raise ApiError(status_code=415, code="unsupported_file_type", message="File type not allowed.") from exc

    return {
        "id": upload_file.id,
        "name": upload_file.name,
        "size": upload_file.size,
        "extension": upload_file.extension,
        "url": file_helpers.get_signed_file_url(upload_file_id=upload_file.id),
        "mime_type": upload_file.mime_type,
        "created_by": upload_file.created_by,
        "created_at": int(upload_file.created_at.timestamp()),
    }


@router.get("/console/api/files/upload")
async def get_console_file_upload_config(request: Request) -> dict[str, Any]:
    await _ensure_console_setup()
    await _resolve_console_account(request)
    return {
        "file_size_limit": dify_config.UPLOAD_FILE_SIZE_LIMIT,
        "batch_count_limit": dify_config.UPLOAD_FILE_BATCH_LIMIT,
        "file_upload_limit": dify_config.BATCH_UPLOAD_LIMIT,
        "image_file_size_limit": dify_config.UPLOAD_IMAGE_FILE_SIZE_LIMIT,
        "video_file_size_limit": dify_config.UPLOAD_VIDEO_FILE_SIZE_LIMIT,
        "audio_file_size_limit": dify_config.UPLOAD_AUDIO_FILE_SIZE_LIMIT,
        "workflow_file_upload_limit": dify_config.WORKFLOW_FILE_UPLOAD_LIMIT,
        "image_file_batch_limit": dify_config.IMAGE_FILE_BATCH_LIMIT,
        "single_chunk_attachment_limit": dify_config.SINGLE_CHUNK_ATTACHMENT_LIMIT,
        "attachment_image_file_size_limit": dify_config.ATTACHMENT_IMAGE_FILE_SIZE_LIMIT,
    }


@router.post("/console/api/files/upload", status_code=201)
async def upload_console_file(
    request: Request,
    file: FastAPIUploadFile = FastAPIFile(...),
    source: Literal["datasets"] | None = Form(default=None),
) -> dict[str, Any]:
    await _ensure_console_setup()
    account = await _resolve_console_account(request)
    if source == "datasets" and not account.is_dataset_editor:
        raise forbidden("forbidden", "Forbidden.")
    if source == "datasets":
        tenant_id = account.current_tenant_id
        if tenant_id is None:
            raise forbidden("forbidden", "Forbidden.")
        features = FeatureService.get_features(tenant_id)
        quota = features.documents_upload_quota
        if features.billing.enabled and 0 < quota.limit <= quota.size:
            raise forbidden("forbidden", "The number of documents has reached the limit of your subscription.")

    if not file.filename:
        raise ApiError(status_code=400, code="filename_not_exists", message="The specified filename does not exist.")

    try:
        upload_file = await asyncio.to_thread(
            FileService(_sync_session_maker()).upload_file,
            filename=file.filename,
            content=await file.read(),
            mimetype=file.content_type or "application/octet-stream",
            user=account,
            source=source,
        )
    except services.errors.file.FileTooLargeError as exc:
        raise ApiError(status_code=413, code="file_too_large", message=exc.description or "File size exceeded.") from exc
    except services.errors.file.UnsupportedFileTypeError as exc:
        raise ApiError(status_code=415, code="unsupported_file_type", message="File type not allowed.") from exc
    except services.errors.file.BlockedFileExtensionError as exc:
        raise ApiError(status_code=400, code="file_extension_blocked", message=exc.description) from exc

    return {
        "id": upload_file.id,
        "name": upload_file.name,
        "size": upload_file.size,
        "extension": upload_file.extension,
        "mime_type": upload_file.mime_type,
        "created_by": upload_file.created_by,
        "created_at": int(upload_file.created_at.timestamp()) if upload_file.created_at else None,
    }


@router.get("/console/api/files/{file_id}/preview")
async def preview_console_file(request: Request, file_id: str) -> dict[str, Any]:
    await _ensure_console_setup()
    await _resolve_console_account(request)
    text = await asyncio.to_thread(FileService(_sync_session_maker()).get_file_preview, file_id)
    return {"content": text}


@router.get("/console/api/files/support-type")
async def get_console_file_support_types(request: Request) -> dict[str, list[str]]:
    await _ensure_console_setup()
    await _resolve_console_account(request)
    return {"allowed_extensions": list(DOCUMENT_EXTENSIONS)}
