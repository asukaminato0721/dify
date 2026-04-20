from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Generator, Iterable, Mapping
from typing import Any, Callable, TypeVar, cast

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from api_server.errors import ApiError
from api_server.routes.inner_api import _ensure_setup
from configs import dify_config
from core.db.session_factory import create_sync_session
from core.plugin.entities.request import (
    RequestFetchAppInfo,
    RequestInvokeApp,
    RequestInvokeEncrypt,
    RequestInvokeLLM,
    RequestInvokeLLMWithStructuredOutput,
    RequestInvokeModeration,
    RequestInvokeParameterExtractorNode,
    RequestInvokeQuestionClassifierNode,
    RequestInvokeRerank,
    RequestInvokeSpeech2Text,
    RequestInvokeSummary,
    RequestInvokeTextEmbedding,
    RequestInvokeTool,
    RequestInvokeTTS,
    RequestRequestUploadFile,
)
from core.tools.entities.tool_entities import ToolProviderType
from core.tools.signature import get_signed_file_url_for_plugin
from models import Account, Tenant
from models.model import DefaultEndUserSessionID, EndUser

router = APIRouter(tags=["inner-api-plugin"])

PayloadT = TypeVar("PayloadT", bound=BaseModel)


def _get_backwards_app():
    from core.plugin.backwards_invocation.app import PluginAppBackwardsInvocation

    return PluginAppBackwardsInvocation


def _get_backwards_base():
    from core.plugin.backwards_invocation.base import BaseBackwardsInvocationResponse

    return BaseBackwardsInvocationResponse


def _get_backwards_encrypt():
    from core.plugin.backwards_invocation.encrypt import PluginEncrypter

    return PluginEncrypter


def _get_backwards_model():
    from core.plugin.backwards_invocation.model import PluginModelBackwardsInvocation

    return PluginModelBackwardsInvocation


def _get_backwards_node():
    from core.plugin.backwards_invocation.node import PluginNodeBackwardsInvocation

    return PluginNodeBackwardsInvocation


def _get_backwards_tool():
    from core.plugin.backwards_invocation.tool import PluginToolBackwardsInvocation

    return PluginToolBackwardsInvocation


class TenantUserPayload(BaseModel):
    tenant_id: str
    user_id: str | None = None


def _check_plugin_inner_api_access(x_inner_api_key: str | None) -> None:
    if not dify_config.PLUGIN_DAEMON_KEY:
        raise ApiError(status_code=404, code="not_found", message="Not found.")
    if not x_inner_api_key or x_inner_api_key != dify_config.INNER_API_KEY_FOR_PLUGIN:
        raise ApiError(status_code=404, code="not_found", message="Not found.")


def _pack_length_prefixed_response(magic_number: int, payload: bytes) -> bytes:
    header_length = 0xA
    data_length = len(payload)
    return struct.pack("<BBHI", magic_number, 0, header_length, data_length) + b"\x00" * 6 + payload


def _length_prefixed_stream(magic_number: int, stream: Iterable[str | bytes]) -> Iterable[bytes]:
    for chunk in stream:
        if isinstance(chunk, str):
            yield _pack_length_prefixed_response(magic_number, chunk.encode("utf-8"))
        else:
            yield _pack_length_prefixed_response(magic_number, chunk)


def _json_or_error_response(builder: Callable[[], Any]) -> dict[str, Any]:
    from graphon.model_runtime.utils.encoders import jsonable_encoder

    BaseBackwardsInvocationResponse = _get_backwards_base()
    try:
        return jsonable_encoder(BaseBackwardsInvocationResponse(data=builder()))
    except Exception as exc:  # pragma: no cover - parity with Flask handlers
        return jsonable_encoder(BaseBackwardsInvocationResponse(error=str(exc)))


def _resolve_plugin_user_sync(tenant_id: str, user_id: str | None) -> EndUser:
    resolved_user_id = user_id or DefaultEndUserSessionID.DEFAULT_SESSION_ID
    is_anonymous = resolved_user_id == DefaultEndUserSessionID.DEFAULT_SESSION_ID
    with create_sync_session() as session:
        user_model = None
        if is_anonymous:
            user_model = session.scalar(
                select(EndUser)
                .where(EndUser.session_id == resolved_user_id, EndUser.tenant_id == tenant_id)
                .limit(1)
            )
        else:
            user_model = session.scalar(
                select(EndUser)
                .where(EndUser.id == resolved_user_id, EndUser.tenant_id == tenant_id)
                .limit(1)
            )

        if not user_model:
            user_model = EndUser(
                tenant_id=tenant_id,
                type="service_api",
                is_anonymous=is_anonymous,
                session_id=resolved_user_id,
            )
            session.add(user_model)
            session.flush()
            session.refresh(user_model)
    return user_model


def _resolve_tenant_sync(tenant_id: str) -> Tenant:
    with create_sync_session() as session:
        tenant = session.get(Tenant, tenant_id)
        if not tenant:
            raise ApiError(status_code=400, code="invalid_tenant", message="tenant not found")
        return tenant


async def _resolve_plugin_user_and_tenant(payload: TenantUserPayload) -> tuple[EndUser, Tenant]:
    user = await asyncio.to_thread(_resolve_plugin_user_sync, payload.tenant_id, payload.user_id)
    tenant = await asyncio.to_thread(_resolve_tenant_sync, payload.tenant_id)
    return user, tenant


def _parse_plugin_payload(data: dict[str, Any], payload_type: type[PayloadT]) -> PayloadT:
    try:
        return payload_type.model_validate(data)
    except Exception as exc:  # pragma: no cover - validation contract
        raise ApiError(status_code=400, code="invalid_payload", message=f"invalid payload: {str(exc)}") from exc


async def _prepare_plugin_request(
    raw_payload: dict[str, Any],
    payload_type: type[PayloadT],
    x_inner_api_key: str | None,
) -> tuple[EndUser | Account, Tenant, PayloadT]:
    await _ensure_setup()
    _check_plugin_inner_api_access(x_inner_api_key)
    tenant_user_payload = TenantUserPayload.model_validate(raw_payload)
    user_model, tenant_model = await _resolve_plugin_user_and_tenant(tenant_user_payload)
    payload = _parse_plugin_payload(raw_payload, payload_type)
    return user_model, tenant_model, payload


@router.post("/inner/api/invoke/llm")
async def plugin_invoke_llm(payload: dict[str, Any], x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key")) -> StreamingResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeLLM, x_inner_api_key)
    stream = await asyncio.to_thread(
        lambda: PluginModelBackwardsInvocation.convert_to_event_stream(
            PluginModelBackwardsInvocation.invoke_llm(user_model.id, tenant_model, parsed)
        )
    )
    return StreamingResponse(_length_prefixed_stream(0xF, stream), media_type="text/event-stream")


@router.post("/inner/api/invoke/llm/structured-output")
async def plugin_invoke_llm_structured(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> StreamingResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeLLMWithStructuredOutput, x_inner_api_key)
    stream = await asyncio.to_thread(
        lambda: PluginModelBackwardsInvocation.convert_to_event_stream(
            PluginModelBackwardsInvocation.invoke_llm_with_structured_output(user_model.id, tenant_model, parsed)
        )
    )
    return StreamingResponse(_length_prefixed_stream(0xF, stream), media_type="text/event-stream")


@router.post("/inner/api/invoke/text-embedding")
async def plugin_invoke_text_embedding(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeTextEmbedding, x_inner_api_key)
    body = await asyncio.to_thread(
        _json_or_error_response,
        lambda: PluginModelBackwardsInvocation.invoke_text_embedding(user_id=user_model.id, tenant=tenant_model, payload=parsed),
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/rerank")
async def plugin_invoke_rerank(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeRerank, x_inner_api_key)
    body = await asyncio.to_thread(
        _json_or_error_response,
        lambda: PluginModelBackwardsInvocation.invoke_rerank(user_id=user_model.id, tenant=tenant_model, payload=parsed),
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/tts")
async def plugin_invoke_tts(payload: dict[str, Any], x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key")) -> StreamingResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeTTS, x_inner_api_key)
    stream = await asyncio.to_thread(
        lambda: PluginModelBackwardsInvocation.convert_to_event_stream(
            PluginModelBackwardsInvocation.invoke_tts(user_id=user_model.id, tenant=tenant_model, payload=parsed)
        )
    )
    return StreamingResponse(_length_prefixed_stream(0xF, stream), media_type="text/event-stream")


@router.post("/inner/api/invoke/speech2text")
async def plugin_invoke_speech2text(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeSpeech2Text, x_inner_api_key)
    body = await asyncio.to_thread(
        _json_or_error_response,
        lambda: PluginModelBackwardsInvocation.invoke_speech2text(user_id=user_model.id, tenant=tenant_model, payload=parsed),
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/moderation")
async def plugin_invoke_moderation(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeModeration, x_inner_api_key)
    body = await asyncio.to_thread(
        _json_or_error_response,
        lambda: PluginModelBackwardsInvocation.invoke_moderation(user_id=user_model.id, tenant=tenant_model, payload=parsed),
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/tool")
async def plugin_invoke_tool(payload: dict[str, Any], x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key")) -> StreamingResponse:
    PluginToolBackwardsInvocation = _get_backwards_tool()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeTool, x_inner_api_key)
    stream = await asyncio.to_thread(
        lambda: PluginToolBackwardsInvocation.convert_to_event_stream(
            PluginToolBackwardsInvocation.invoke_tool(
                tenant_id=tenant_model.id,
                user_id=user_model.id,
                tool_type=ToolProviderType.value_of(parsed.tool_type),
                provider=parsed.provider,
                tool_name=parsed.tool,
                tool_parameters=parsed.tool_parameters,
                credential_id=parsed.credential_id,
            )
        )
    )
    return StreamingResponse(_length_prefixed_stream(0xF, stream), media_type="text/event-stream")


@router.post("/inner/api/invoke/parameter-extractor")
async def plugin_invoke_parameter_extractor(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginNodeBackwardsInvocation = _get_backwards_node()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeParameterExtractorNode, x_inner_api_key)
    body = await asyncio.to_thread(
        _json_or_error_response,
        lambda: PluginNodeBackwardsInvocation.invoke_parameter_extractor(
            tenant_id=tenant_model.id,
            user_id=user_model.id,
            parameters=parsed.parameters,
            model_config=parsed.model,
            instruction=parsed.instruction,
            query=parsed.query,
        ),
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/question-classifier")
async def plugin_invoke_question_classifier(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginNodeBackwardsInvocation = _get_backwards_node()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeQuestionClassifierNode, x_inner_api_key)
    body = await asyncio.to_thread(
        _json_or_error_response,
        lambda: PluginNodeBackwardsInvocation.invoke_question_classifier(
            tenant_id=tenant_model.id,
            user_id=user_model.id,
            query=parsed.query,
            model_config=parsed.model,
            classes=parsed.classes,
            instruction=parsed.instruction,
        ),
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/app")
async def plugin_invoke_app(payload: dict[str, Any], x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key")) -> StreamingResponse:
    PluginAppBackwardsInvocation = _get_backwards_app()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeApp, x_inner_api_key)
    stream = await asyncio.to_thread(
        lambda: PluginAppBackwardsInvocation.convert_to_event_stream(
            PluginAppBackwardsInvocation.invoke_app(
                app_id=parsed.app_id,
                user_id=user_model.id,
                tenant_id=tenant_model.id,
                conversation_id=parsed.conversation_id,
                query=parsed.query,
                stream=parsed.response_mode == "streaming",
                inputs=parsed.inputs,
                files=parsed.files,
            )
        )
    )
    return StreamingResponse(_length_prefixed_stream(0xF, stream), media_type="text/event-stream")


@router.post("/inner/api/invoke/encrypt")
async def plugin_invoke_encrypt(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    BaseBackwardsInvocationResponse = _get_backwards_base()
    PluginEncrypter = _get_backwards_encrypt()
    _, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeEncrypt, x_inner_api_key)
    body = await asyncio.to_thread(
        lambda: BaseBackwardsInvocationResponse(data=PluginEncrypter.invoke_encrypt(tenant_model, parsed)).model_dump()
    )
    return JSONResponse(content=body)


@router.post("/inner/api/invoke/summary")
async def plugin_invoke_summary(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    BaseBackwardsInvocationResponse = _get_backwards_base()
    PluginModelBackwardsInvocation = _get_backwards_model()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestInvokeSummary, x_inner_api_key)
    body = await asyncio.to_thread(
        lambda: BaseBackwardsInvocationResponse(
            data={"summary": PluginModelBackwardsInvocation.invoke_summary(user_id=user_model.id, tenant=tenant_model, payload=parsed)}
        ).model_dump()
    )
    return JSONResponse(content=body)


@router.post("/inner/api/upload/file/request")
async def plugin_upload_file_request(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    BaseBackwardsInvocationResponse = _get_backwards_base()
    user_model, tenant_model, parsed = await _prepare_plugin_request(payload, RequestRequestUploadFile, x_inner_api_key)
    body = BaseBackwardsInvocationResponse(
        data={
            "url": get_signed_file_url_for_plugin(
                filename=parsed.filename,
                mimetype=parsed.mimetype,
                tenant_id=tenant_model.id,
                user_id=user_model.id,
            )
        }
    ).model_dump()
    return JSONResponse(content=body)


@router.post("/inner/api/fetch/app/info")
async def plugin_fetch_app_info(
    payload: dict[str, Any],
    x_inner_api_key: str | None = Header(default=None, alias="X-Inner-Api-Key"),
) -> JSONResponse:
    PluginAppBackwardsInvocation = _get_backwards_app()
    BaseBackwardsInvocationResponse = _get_backwards_base()
    _, tenant_model, parsed = await _prepare_plugin_request(payload, RequestFetchAppInfo, x_inner_api_key)
    body = await asyncio.to_thread(
        lambda: BaseBackwardsInvocationResponse(
            data=PluginAppBackwardsInvocation.fetch_app_info(parsed.app_id, tenant_model.id)
        ).model_dump()
    )
    return JSONResponse(content=body)
