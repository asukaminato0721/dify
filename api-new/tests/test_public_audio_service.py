from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest

import api_server.services.audio as audio_module
from api_server.models.app import AppMode
from api_server.services.audio import PublicAudioService
from graphon.model_runtime.entities.model_entities import ModelType


class _ModelInstanceStub:
    calls: list[tuple[str, object]]

    def __init__(self) -> None:
        self.calls = []

    def invoke_speech2text(self, *, file: object) -> str:
        self.calls.append(("speech2text", file))
        return "transcribed text"

    def get_tts_voices(self) -> list[dict[str, str]]:
        self.calls.append(("voices", None))
        return [{"value": "voice-1"}]

    def invoke_tts(self, *, content_text: str, voice: str) -> bytes:
        self.calls.append(("tts", (content_text, voice)))
        return b"mp3-bytes"


class _ModelManagerStub:
    model_instance: _ModelInstanceStub

    def __init__(self, model_instance: _ModelInstanceStub) -> None:
        self.model_instance = model_instance

    def get_default_model_instance(self, tenant_id: str, model_type: object) -> _ModelInstanceStub:
        self.model_instance.calls.append(("default-model", (tenant_id, model_type)))
        return self.model_instance


def _context_with_model_config() -> object:
    feature_dict = {
        "speech_to_text": {"enabled": True},
        "text_to_speech": {"enabled": True},
    }
    return SimpleNamespace(
        app=SimpleNamespace(mode=AppMode.CHAT, tenant_id="tenant-1", id="app-1"),
        end_user=SimpleNamespace(id="end-user-1"),
        app_model_config=SimpleNamespace(to_feature_dict=lambda: feature_dict),
        workflow=None,
    )


@pytest.mark.asyncio
async def test_transcribe_audio_offloads_model_lookup_and_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Callable[..., object], tuple[object, ...], dict[str, object]]] = []
    model_instance = _ModelInstanceStub()
    context = _context_with_model_config()

    async def fake_to_thread(
        func: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(audio_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        audio_module.ModelManager,
        "for_tenant",
        lambda tenant_id, user_id=None: _ModelManagerStub(model_instance),
    )

    response = await PublicAudioService.transcribe_audio(
        context=cast(object, context),
        filename="voice.mp3",
        content_type="audio/mpeg",
        content=b"audio-data",
    )

    assert response == {"text": "transcribed text"}
    assert len(calls) == 2
    assert calls[0][0].__name__ == "get_default_model_instance"
    assert calls[0][1] == ("tenant-1", ModelType.SPEECH2TEXT)
    assert calls[1][0].__name__ == "invoke_speech2text"
    assert calls[1][2]["file"].name == "voice.mp3"


@pytest.mark.asyncio
async def test_synthesize_audio_offloads_model_lookup_and_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Callable[..., object], tuple[object, ...], dict[str, object]]] = []
    model_instance = _ModelInstanceStub()
    context = _context_with_model_config()

    async def fake_to_thread(
        func: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(audio_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        audio_module.ModelManager,
        "for_tenant",
        lambda tenant_id, user_id=None: _ModelManagerStub(model_instance),
    )

    result = await PublicAudioService.synthesize_audio(
        context=cast(object, context),
        text="  hello world  ",
        voice=None,
        message_id=None,
    )

    assert result == b"mp3-bytes"
    assert len(calls) == 3
    assert calls[0][0].__name__ == "get_default_model_instance"
    assert calls[0][1] == ("tenant-1", ModelType.TTS)
    assert calls[1][0].__name__ == "get_tts_voices"
    assert calls[2][0].__name__ == "invoke_tts"
    assert calls[2][2] == {"content_text": "hello world", "voice": "voice-1"}
