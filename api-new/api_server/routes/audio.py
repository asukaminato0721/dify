"""FastAPI public audio routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api_server.services.audio import PublicAudioService
from api_server.services.webapp_context import WebappContextService

router = APIRouter(tags=["audio"])


class TextToAudioPayload(BaseModel):
    message_id: str | None = Field(default=None)
    voice: str | None = Field(default=None)
    text: str | None = Field(default=None)
    streaming: bool | None = Field(default=None)


@router.post("/api/audio-to-text")
async def audio_to_text(request: Request, file: UploadFile = File(...)) -> dict[str, str]:
    context = await WebappContextService.resolve(request)
    content = await file.read()
    return await PublicAudioService.transcribe_audio(
        context=context,
        filename=file.filename or "audio",
        content_type=file.content_type or "",
        content=content,
    )


@router.post("/api/text-to-audio", response_model=None)
async def text_to_audio(
    request: Request,
    payload: TextToAudioPayload,
) -> JSONResponse | StreamingResponse | Response:
    context = await WebappContextService.resolve(request)
    result = await PublicAudioService.synthesize_audio(
        context=context,
        text=payload.text,
        voice=payload.voice,
        message_id=payload.message_id,
    )
    if isinstance(result, bytes):
        return Response(content=result, media_type="audio/mpeg")
    return StreamingResponse(result, media_type="audio/mpeg")
