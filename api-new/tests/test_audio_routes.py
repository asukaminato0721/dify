from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from api_server.routes.audio import TextToAudioPayload, audio_to_text, text_to_audio


def _build_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
        }
    )


class _FakeUploadFile:
    filename: str
    content_type: str
    _content: bytes

    def __init__(self, *, filename: str, content_type: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


async def test_audio_to_text_route_uses_service() -> None:
    context = object()
    upload = _FakeUploadFile(filename="voice.mp3", content_type="audio/mpeg", content=b"data")
    with (
        patch("api_server.routes.audio.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.audio.PublicAudioService.transcribe_audio",
            new=AsyncMock(return_value={"text": "hello"}),
        ) as transcribe_mock,
    ):
        response = await audio_to_text(_build_request("/api/audio-to-text"), cast(Any, upload))

    assert response == {"text": "hello"}
    transcribe_mock.assert_awaited_once()


def _audio_chunks() -> Iterator[bytes]:
    yield b"chunk-1"
    yield b"chunk-2"


async def test_text_to_audio_route_streams_iterable_result() -> None:
    context = object()
    with (
        patch("api_server.routes.audio.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.audio.PublicAudioService.synthesize_audio",
            new=AsyncMock(return_value=_audio_chunks()),
        ),
    ):
        response = await text_to_audio(_build_request("/api/text-to-audio"), TextToAudioPayload(text="hello"))

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "audio/mpeg"


async def test_text_to_audio_route_returns_bytes_response() -> None:
    context = object()
    with (
        patch("api_server.routes.audio.WebappContextService.resolve", new=AsyncMock(return_value=context)),
        patch(
            "api_server.routes.audio.PublicAudioService.synthesize_audio",
            new=AsyncMock(return_value=b"mp3-data"),
        ),
    ):
        response = await text_to_audio(_build_request("/api/text-to-audio"), TextToAudioPayload(text="hello"))

    assert isinstance(response, Response)
    assert response.body == b"mp3-data"
    assert response.media_type == "audio/mpeg"
