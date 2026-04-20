"""FastAPI-native public audio service."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Iterable
from typing import cast

from sqlalchemy import select

from api_server.errors import bad_request, not_found
from api_server.models.app import AppMode, Message
from api_server.services.webapp_context import WebappContext
from constants import AUDIO_EXTENSIONS
from core.errors.error import ProviderTokenNotInitError
from core.model_manager import ModelInstance, ModelManager
from extensions.ext_database import db
from graphon.model_runtime.entities.model_entities import ModelType
from services.errors.audio import (
    AudioTooLargeServiceError,
    NoAudioUploadedServiceError,
    ProviderNotSupportSpeechToTextServiceError,
    ProviderNotSupportTextToSpeechServiceError,
    UnsupportedAudioTypeServiceError,
)

FILE_SIZE_MB = 30
FILE_SIZE_LIMIT = FILE_SIZE_MB * 1024 * 1024
_AUDIO_MIME_TYPES = {f"audio/{ext.lower()}" for ext in AUDIO_EXTENSIONS} | {"audio/mpeg"}


class PublicAudioService:
    """Execute public STT/TTS requests using the active FastAPI webapp context.

    Model lookup and model-runtime invocation are still sync in the shared
    model stack, so the FastAPI surface must offload them from the event loop.
    """

    @staticmethod
    def _get_speech_to_text_feature(*, context: WebappContext) -> dict[str, object]:
        if context.app.mode in {AppMode.ADVANCED_CHAT, AppMode.WORKFLOW}:
            if context.workflow is None:
                raise bad_request("speech_to_text_disabled", "Speech to text is not enabled.")
            return cast(dict[str, object], context.workflow.features_dict.get("speech_to_text", {"enabled": False}))

        if context.app_model_config is None:
            raise bad_request("speech_to_text_disabled", "Speech to text is not enabled.")
        return cast(
            dict[str, object],
            context.app_model_config.to_feature_dict().get("speech_to_text", {"enabled": False}),
        )

    @staticmethod
    def _get_text_to_speech_feature(*, context: WebappContext) -> dict[str, object]:
        if context.app.mode in {AppMode.ADVANCED_CHAT, AppMode.WORKFLOW}:
            if context.workflow is None:
                raise bad_request("text_to_speech_disabled", "Text to speech is not enabled.")
            return cast(dict[str, object], context.workflow.features_dict.get("text_to_speech", {"enabled": False}))

        if context.app_model_config is None:
            raise bad_request("text_to_speech_disabled", "Text to speech is not enabled.")
        return cast(
            dict[str, object],
            context.app_model_config.to_feature_dict().get("text_to_speech", {"enabled": False}),
        )

    @classmethod
    def _get_model_manager(cls, *, context: WebappContext) -> ModelManager:
        return ModelManager.for_tenant(tenant_id=context.app.tenant_id, user_id=context.end_user.id)

    @classmethod
    async def _get_default_model_instance(
        cls,
        *,
        context: WebappContext,
        model_type: ModelType,
    ) -> ModelInstance | None:
        """Return the configured runtime model or `None` when the tenant has no default model."""

        try:
            return await asyncio.to_thread(
                cls._get_model_manager(context=context).get_default_model_instance,
                context.app.tenant_id,
                model_type,
            )
        except ProviderTokenNotInitError:
            return None

    @staticmethod
    async def _invoke_speech_to_text(*, model_instance: ModelInstance, filename: str, content: bytes) -> str:
        buffer = io.BytesIO(content)
        buffer.name = filename
        return await asyncio.to_thread(model_instance.invoke_speech2text, file=buffer)

    @staticmethod
    async def _resolve_tts_voice(*, model_instance: ModelInstance) -> str | None:
        voices = await asyncio.to_thread(model_instance.get_tts_voices)
        if not voices:
            return None
        return cast(str | None, voices[0].get("value"))

    @staticmethod
    async def _invoke_tts(*, model_instance: ModelInstance, text: str, voice: str) -> bytes | Iterable[bytes]:
        result = await asyncio.to_thread(model_instance.invoke_tts, content_text=text, voice=voice)
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        return cast(Iterable[bytes], result)

    @classmethod
    async def transcribe_audio(
        cls,
        *,
        context: WebappContext,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, str]:
        feature = cls._get_speech_to_text_feature(context=context)
        if not feature.get("enabled"):
            raise bad_request("speech_to_text_disabled", "Speech to text is not enabled.")
        if not filename:
            raise NoAudioUploadedServiceError()
        if content_type.lower() not in _AUDIO_MIME_TYPES:
            raise UnsupportedAudioTypeServiceError()
        if len(content) > FILE_SIZE_LIMIT:
            raise AudioTooLargeServiceError(f"Audio size larger than {FILE_SIZE_MB} mb")

        model_instance = await cls._get_default_model_instance(
            context=context,
            model_type=ModelType.SPEECH2TEXT,
        )
        if model_instance is None:
            raise ProviderNotSupportSpeechToTextServiceError()

        text = await cls._invoke_speech_to_text(
            model_instance=model_instance,
            filename=filename,
            content=content,
        )
        return {"text": text}

    @classmethod
    async def synthesize_audio(
        cls,
        *,
        context: WebappContext,
        text: str | None,
        voice: str | None,
        message_id: str | None,
    ) -> bytes | Iterable[bytes]:
        feature = cls._get_text_to_speech_feature(context=context)
        if not feature.get("enabled"):
            raise bad_request("text_to_speech_disabled", "TTS is not enabled.")

        resolved_voice = voice or cast(str | None, feature.get("voice"))
        resolved_text = text
        if message_id is not None:
            async with db.session_context() as session:
                message = await session.scalar(
                    select(Message).where(Message.id == message_id, Message.app_id == context.app.id).limit(1)
                )
            if message is None:
                raise not_found("message_not_found", "Message not found.")
            if message.answer == "" and message.status in {"normal", "paused"}:
                raise bad_request("message_not_ready", "Message audio is not available yet.")
            resolved_text = message.answer

        if resolved_text is None:
            raise bad_request("text_required", "Text is required.")

        model_instance = await cls._get_default_model_instance(
            context=context,
            model_type=ModelType.TTS,
        )
        if model_instance is None:
            raise ProviderNotSupportTextToSpeechServiceError()

        if not resolved_voice:
            resolved_voice = await cls._resolve_tts_voice(model_instance=model_instance)
            if not resolved_voice:
                raise bad_request("tts_voice_unavailable", "Sorry, no voice available.")

        return await cls._invoke_tts(model_instance=model_instance, text=resolved_text.strip(), voice=resolved_voice)
