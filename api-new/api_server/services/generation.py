"""Public generation services for the FastAPI runtime.

Completion and plain-chat requests are handled natively in this module.
Workflow-backed public modes still depend on the copied execution stack, so
they currently cross a narrow compatibility bridge while the async-native
workflow port continues.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from sqlalchemy import select

from api_server.errors import bad_request, forbidden, not_found, service_unavailable
from api_server.models.app import AppModelConfig, Conversation, Message
from api_server.services.webapp_context import WebappContext
from core.app.app_config.base_app_config_manager import BaseAppConfigManager
from core.app.app_config.common.sensitive_word_avoidance.manager import SensitiveWordAvoidanceConfigManager
from core.app.app_config.easy_ui_based_app.dataset.manager import DatasetConfigManager
from core.app.app_config.easy_ui_based_app.model_config.converter import ModelConfigConverter
from core.app.app_config.easy_ui_based_app.model_config.manager import ModelConfigManager
from core.app.app_config.easy_ui_based_app.prompt_template.manager import PromptTemplateConfigManager
from core.app.app_config.easy_ui_based_app.variables.manager import BasicVariablesConfigManager
from core.app.entities.app_invoke_entities import InvokeFrom
from core.app.apps.chat.app_config_manager import ChatAppConfig
from core.app.apps.completion.app_config_manager import CompletionAppConfig
from core.app.entities.app_invoke_entities import ModelConfigWithCredentialsEntity
from core.app.entities.task_entities import (
    ChatbotAppBlockingResponse,
    ChatbotAppStreamResponse,
    CompletionAppBlockingResponse,
    CompletionAppStreamResponse,
    MessageEndStreamResponse,
    MessageStreamResponse,
)
from core.model_manager import ModelInstance
from core.prompt.advanced_prompt_transform import AdvancedPromptTransform
from core.prompt.entities.advanced_prompt_entities import CompletionModelPromptTemplate, MemoryConfig
from core.prompt.simple_prompt_transform import SimplePromptTransform
from extensions.ext_database import db
from graphon.prompt_entities import ChatModelMessage
from graphon.model_runtime.entities.llm_entities import LLMResult, LLMResultChunk, LLMUsage
from graphon.model_runtime.entities.message_entities import (
    AssistantPromptMessage,
    PromptMessage,
    UserPromptMessage,
)
from libs.flask_utils import set_login_user
from libs.orjson import orjson_dumps
from models.model import App as LegacyApp
from models.model import AppMode as LegacyAppMode
from models.model import AppModelConfigDict
from models.model import EndUser as LegacyEndUser


def _timestamp(value: datetime | None) -> int:
    current_value = value or datetime.now(UTC)
    if current_value.tzinfo is None:
        current_value = current_value.replace(tzinfo=UTC)
    return int(current_value.timestamp())


def _config_dict(app_model_config: AppModelConfig) -> AppModelConfigDict:
    config = app_model_config.to_feature_dict()
    prompt_type = "advanced" if config.get("chat_prompt_config") or config.get("completion_prompt_config") else "simple"
    config["prompt_type"] = prompt_type
    return cast(AppModelConfigDict, config)


@dataclass(frozen=True, slots=True)
class _HistoryMessage:
    id: str
    query: str
    answer: str
    parent_message_id: str | None


@dataclass(frozen=True, slots=True)
class _LegacyAppProxy:
    """Minimal app view required by the copied compatibility generators."""

    id: str
    tenant_id: str
    mode: str
    workflow_id: str | None
    is_agent: bool
    max_active_requests: int | None


class _CompatibilityGenerationArgs(TypedDict, total=False):
    """Public generation payload passed into the copied execution bridge."""

    inputs: dict[str, Any]
    query: str
    files: list[dict[str, Any]]
    conversation_id: str
    parent_message_id: str
    auto_generate_name: bool


class _ConversationMemoryAdapter:
    def __init__(self, *, messages: list[_HistoryMessage]) -> None:
        self._messages = messages

    @staticmethod
    def _extract_thread(messages: list[_HistoryMessage]) -> list[_HistoryMessage]:
        from constants import UUID_NIL

        thread_messages: list[_HistoryMessage] = []
        next_message_id: str | None = None
        for message in messages:
            if not message.parent_message_id:
                thread_messages.append(message)
                break
            if next_message_id is None:
                thread_messages.append(message)
                next_message_id = message.parent_message_id
                continue
            if next_message_id in {message.id, UUID_NIL}:
                thread_messages.append(message)
                next_message_id = message.parent_message_id
        thread_messages.reverse()
        return thread_messages

    def get_history_prompt_messages(self, *, max_token_limit: int = 2000, message_limit: int | None = None) -> list[PromptMessage]:
        del max_token_limit
        thread_messages = self._extract_thread(self._messages)
        if message_limit is not None and message_limit > 0:
            thread_messages = thread_messages[-message_limit:]
        prompt_messages: list[PromptMessage] = []
        for message in thread_messages:
            prompt_messages.append(UserPromptMessage(content=message.query))
            prompt_messages.append(AssistantPromptMessage(content=message.answer))
        return prompt_messages

    def get_history_prompt_text(
        self,
        *,
        human_prefix: str = "Human",
        ai_prefix: str = "Assistant",
        max_token_limit: int = 2000,
        message_limit: int | None = None,
    ) -> str:
        del max_token_limit
        thread_messages = self._extract_thread(self._messages)
        if message_limit is not None and message_limit > 0:
            thread_messages = thread_messages[-message_limit:]
        lines: list[str] = []
        for message in thread_messages:
            lines.append(f"{human_prefix}: {message.query}")
            lines.append(f"{ai_prefix}: {message.answer}")
        return "\n".join(lines)


def _build_completion_config(
    context: WebappContext,
    *,
    config_dict_override: AppModelConfigDict | None = None,
) -> CompletionAppConfig:
    if context.app_model_config is None:
        raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

    config_dict = config_dict_override or _config_dict(context.app_model_config)
    app_mode = LegacyAppMode.value_of(str(context.app.mode))
    app_config = CompletionAppConfig(
        tenant_id=context.app.tenant_id,
        app_id=context.app.id,
        app_mode=app_mode,
        app_model_config_from="app-latest-config",
        app_model_config_id=context.app_model_config.id,
        app_model_config_dict=config_dict,
        model=ModelConfigManager.convert(config=config_dict),
        prompt_template=PromptTemplateConfigManager.convert(config=config_dict),
        sensitive_word_avoidance=SensitiveWordAvoidanceConfigManager.convert(config=config_dict),
        dataset=DatasetConfigManager.convert(config=config_dict),
        additional_features=BaseAppConfigManager.convert_features(config_dict, app_mode),
    )
    app_config.variables, app_config.external_data_variables = BasicVariablesConfigManager.convert(config=config_dict)
    return app_config


def _build_chat_config(context: WebappContext) -> ChatAppConfig:
    if context.app_model_config is None:
        raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

    config_dict = _config_dict(context.app_model_config)
    app_mode = LegacyAppMode.value_of(str(context.app.mode))
    app_config = ChatAppConfig(
        tenant_id=context.app.tenant_id,
        app_id=context.app.id,
        app_mode=app_mode,
        app_model_config_from="app-latest-config",
        app_model_config_id=context.app_model_config.id,
        app_model_config_dict=config_dict,
        model=ModelConfigManager.convert(config=config_dict),
        prompt_template=PromptTemplateConfigManager.convert(config=config_dict),
        sensitive_word_avoidance=SensitiveWordAvoidanceConfigManager.convert(config=config_dict),
        dataset=DatasetConfigManager.convert(config=config_dict),
        additional_features=BaseAppConfigManager.convert_features(config_dict, app_mode),
    )
    app_config.variables, app_config.external_data_variables = BasicVariablesConfigManager.convert(config=config_dict)
    return app_config


def _ensure_supported_features(*, files: list[dict[str, Any]] | None, dataset_enabled: bool, external_tools_enabled: bool) -> None:
    if files:
        raise service_unavailable("files_not_supported", "File generation inputs are not ported to the FastAPI runtime yet.")
    if dataset_enabled:
        raise service_unavailable(
            "dataset_retrieval_unavailable",
            "Dataset-backed generation is not ported to the FastAPI runtime yet.",
        )
    if external_tools_enabled:
        raise service_unavailable(
            "external_data_tools_unavailable",
            "External data tool generation is not ported to the FastAPI runtime yet.",
        )


def _build_legacy_app_proxy(context: WebappContext) -> _LegacyAppProxy:
    return _LegacyAppProxy(
        id=context.app.id,
        tenant_id=context.app.tenant_id,
        mode=str(context.app.mode),
        workflow_id=context.app.workflow_id,
        is_agent=context.app.mode == context.app.mode.AGENT_CHAT,
        max_active_requests=None,
    )


def _run_compat_public_generation_blocking(
    *,
    context: WebappContext,
    args: _CompatibilityGenerationArgs,
    streaming: bool,
) -> Mapping[str, Any] | Iterator[str]:
    """Run the copied workflow-capable generators inside the local Flask shim."""

    from flask import Flask
    from services.app_generate_service import AppGenerateService

    compat_app = Flask("fastapi-public-generation")
    with compat_app.app_context():
        set_login_user(context.end_user)
        response = AppGenerateService.generate(
            app_model=cast(LegacyApp, _build_legacy_app_proxy(context)),
            user=cast(LegacyEndUser, context.end_user),
            args=args,
            invoke_from=InvokeFrom.WEB_APP,
            streaming=streaming,
        )
    return cast(Mapping[str, Any] | Iterator[str], response)


async def _run_compat_public_generation(
    *,
    context: WebappContext,
    args: _CompatibilityGenerationArgs,
    streaming: bool,
) -> Mapping[str, Any] | Iterator[str]:
    return await asyncio.to_thread(
        _run_compat_public_generation_blocking,
        context=context,
        args=args,
        streaming=streaming,
    )


async def _create_chat_records(
    *,
    context: WebappContext,
    app_model_config_id: str,
    query: str,
    inputs: dict[str, Any],
    conversation_id: str | None,
    parent_message_id: str | None,
    introduction: str | None,
) -> tuple[Conversation, Message]:
    async with db.session_context() as session:
        conversation = None
        if conversation_id is not None:
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.app_id == context.app.id,
                    Conversation.from_source == "api",
                    Conversation.from_end_user_id == context.end_user.id,
                    Conversation.is_deleted.is_(False),
                )
            )
            if conversation is None:
                raise bad_request("conversation_not_exists", "Conversation Not Exists.")

        if conversation is None:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                app_id=context.app.id,
                app_model_config_id=app_model_config_id,
                mode=str(context.app.mode),
                name=(query[:20] + "…") if len(query) > 20 else query,
                inputs=inputs,
                introduction=introduction,
                status="normal",
                invoke_from="web-app",
                from_source="api",
                from_end_user_id=context.end_user.id,
                from_account_id=None,
                is_deleted=False,
            )
            session.add(conversation)
            await session.flush()

        message = Message(
            id=str(uuid.uuid4()),
            app_id=context.app.id,
            conversation_id=conversation.id,
            inputs=inputs,
            query=query,
            answer="",
            parent_message_id=parent_message_id,
            status="normal",
            error=None,
            message_metadata=None,
            from_source="api",
            from_end_user_id=context.end_user.id,
            from_account_id=None,
        )
        session.add(message)
        await session.flush()
        await session.refresh(conversation)
        await session.refresh(message)
        return conversation, message


async def _create_completion_message(
    *,
    context: WebappContext,
    query: str,
    inputs: dict[str, Any],
) -> Message:
    async with db.session_context() as session:
        message = Message(
            id=str(uuid.uuid4()),
            app_id=context.app.id,
            conversation_id=str(uuid.uuid4()),
            inputs=inputs,
            query=query,
            answer="",
            parent_message_id=None,
            status="normal",
            error=None,
            message_metadata=None,
            from_source="api",
            from_end_user_id=context.end_user.id,
            from_account_id=None,
        )
        session.add(message)
        await session.flush()
        await session.refresh(message)
        return message


async def _load_owned_message(*, app_id: str, end_user_id: str, message_id: str) -> Message:
    async with db.session_context() as session:
        message = await session.scalar(
            select(Message).where(
                Message.id == message_id,
                Message.app_id == app_id,
                Message.from_source == "api",
                Message.from_end_user_id == end_user_id,
            )
        )
    if message is None:
        raise not_found("message_not_found", "Message not found.")
    return message


async def _load_chat_history(*, conversation_id: str) -> list[_HistoryMessage]:
    async with db.session_context() as session:
        rows = (
            await session.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(20)
            )
        ).all()
    return [
        _HistoryMessage(
            id=row.id,
            query=row.query,
            answer=row.answer,
            parent_message_id=row.parent_message_id,
        )
        for row in rows
        if row.answer
    ]


async def _save_message_result(*, message_id: str, answer: str, usage: LLMUsage | None) -> None:
    async with db.session_context() as session:
        message = await session.scalar(select(Message).where(Message.id == message_id).limit(1))
        if message is None:
            return
        message.answer = answer
        message.status = "normal"
        if usage is not None:
            message.message_metadata = json.dumps({"usage": usage.model_dump(mode="json")})
        session.add(message)
        await session.flush()


def _build_completion_prompt_messages(
    *,
    app_config: CompletionAppConfig,
    model_conf: ModelConfigWithCredentialsEntity,
    inputs: dict[str, Any],
    query: str,
) -> tuple[list[PromptMessage], list[str] | None]:
    transform = (
        AdvancedPromptTransform()
        if app_config.prompt_template.prompt_type == app_config.prompt_template.PromptType.ADVANCED
        else SimplePromptTransform()
    )
    if isinstance(transform, SimplePromptTransform):
        return transform.get_prompt(
            app_mode=app_config.app_mode,
            prompt_template_entity=app_config.prompt_template,
            inputs={key: str(value) for key, value in inputs.items()},
            query=query,
            files=[],
            context=None,
            memory=None,
            model_config=model_conf,
        )
    completion_prompt_template = app_config.prompt_template.advanced_completion_prompt_template
    if completion_prompt_template is None:
        raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")
    return (
        transform.get_prompt(
            prompt_template=CompletionModelPromptTemplate(
                text=completion_prompt_template.prompt,
                role_prefix=completion_prompt_template.role_prefix,
            ),
            inputs={key: str(value) for key, value in inputs.items()},
            query=query,
            files=[],
            context=None,
            memory_config=None,
            memory=None,
            model_config=model_conf,
        ),
        model_conf.stop,
    )


def _build_chat_prompt_messages(
    *,
    app_config: ChatAppConfig,
    model_conf: ModelConfigWithCredentialsEntity,
    inputs: dict[str, Any],
    query: str,
    history_messages: list[_HistoryMessage],
) -> tuple[list[PromptMessage], list[str] | None]:
    memory_adapter = _ConversationMemoryAdapter(messages=history_messages) if history_messages else None
    transform = (
        AdvancedPromptTransform()
        if app_config.prompt_template.prompt_type == app_config.prompt_template.PromptType.ADVANCED
        else SimplePromptTransform()
    )
    if isinstance(transform, SimplePromptTransform):
        return transform.get_prompt(
            app_mode=app_config.app_mode,
            prompt_template_entity=app_config.prompt_template,
            inputs={key: str(value) for key, value in inputs.items()},
            query=query,
            files=[],
            context=None,
            memory=cast(Any, memory_adapter),
            model_config=model_conf,
        )
    chat_prompt_template = app_config.prompt_template.advanced_chat_prompt_template
    if chat_prompt_template is None:
        raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")
    memory_config = MemoryConfig(window=MemoryConfig.WindowConfig(enabled=True, size=10))
    advanced_messages = [ChatModelMessage(text=item.text, role=item.role) for item in chat_prompt_template.messages]
    prompt_messages = transform.get_prompt(
        prompt_template=advanced_messages,
        inputs={key: str(value) for key, value in inputs.items()},
        query=query,
        files=[],
        context=None,
        memory_config=memory_config,
        memory=cast(Any, memory_adapter),
        model_config=model_conf,
    )
    return prompt_messages, model_conf.stop


def _encode_sse(payload: dict[str, Any]) -> str:
    return f"data: {orjson_dumps(payload)}\n\n"


async def _next_chunk(iterator: Iterator[LLMResultChunk]) -> LLMResultChunk | None:
    def _next() -> LLMResultChunk | None:
        try:
            return next(iterator)
        except StopIteration:
            return None

    return await asyncio.to_thread(_next)


class AsyncWebGenerationService:
    """Async-native completion/chat generation for the FastAPI runtime."""

    @classmethod
    async def run_completion(
        cls,
        *,
        context: WebappContext,
        inputs: dict[str, Any],
        query: str,
        files: list[dict[str, Any]] | None,
        streaming: bool,
    ) -> ChatbotAppBlockingResponse | CompletionAppBlockingResponse | AsyncIterator[str]:
        app_config = _build_completion_config(context)
        _ensure_supported_features(
            files=files,
            dataset_enabled=bool(app_config.dataset and app_config.dataset.dataset_ids),
            external_tools_enabled=bool(app_config.external_data_variables),
        )
        model_conf = await asyncio.to_thread(ModelConfigConverter.convert, app_config)
        prompt_messages, stop = _build_completion_prompt_messages(
            app_config=app_config,
            model_conf=model_conf,
            inputs=inputs,
            query=query,
        )
        message = await _create_completion_message(context=context, query=query, inputs=inputs)
        task_id = str(uuid.uuid4())

        if not streaming:
            llm_result = await asyncio.to_thread(
                cls._invoke_blocking,
                model_conf,
                prompt_messages,
                stop,
            )
            await _save_message_result(
                message_id=message.id,
                answer=llm_result.message.get_text_content(),
                usage=llm_result.usage,
            )
            return CompletionAppBlockingResponse(
                task_id=task_id,
                data=CompletionAppBlockingResponse.Data(
                    id=message.id,
                    mode="completion",
                    message_id=message.id,
                    answer=llm_result.message.get_text_content(),
                    metadata={"usage": llm_result.usage.model_dump(mode="json")},
                    created_at=_timestamp(message.created_at),
                ),
            )

        return cls._stream_completion(
            task_id=task_id,
            message=message,
            model_conf=model_conf,
            prompt_messages=prompt_messages,
            stop=stop,
        )

    @classmethod
    async def run_more_like_this(
        cls,
        *,
        context: WebappContext,
        message_id: str,
        streaming: bool,
    ) -> CompletionAppBlockingResponse | AsyncIterator[str]:
        if context.app_model_config is None:
            raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")

        feature_dict = context.app_model_config.to_feature_dict()
        more_like_this_dict = feature_dict.get("more_like_this", {"enabled": False})
        if not more_like_this_dict.get("enabled", False):
            raise forbidden(
                "app_more_like_this_disabled",
                "The 'More like this' feature is disabled. Please refresh your page.",
            )

        source_message = await _load_owned_message(
            app_id=context.app.id,
            end_user_id=context.end_user.id,
            message_id=message_id,
        )

        config_dict = _config_dict(context.app_model_config)
        if source_message.override_model_configs:
            try:
                config_dict = cast(AppModelConfigDict, json.loads(source_message.override_model_configs))
            except json.JSONDecodeError:
                config_dict = _config_dict(context.app_model_config)
        model_dict = dict(cast(dict[str, Any], config_dict.get("model", {})))
        completion_params = dict(cast(dict[str, Any], model_dict.get("completion_params", {})))
        completion_params["temperature"] = 0.9
        model_dict["completion_params"] = completion_params
        config_dict["model"] = cast(Any, model_dict)

        app_config = _build_completion_config(context, config_dict_override=config_dict)
        _ensure_supported_features(
            files=None,
            dataset_enabled=bool(app_config.dataset and app_config.dataset.dataset_ids),
            external_tools_enabled=bool(app_config.external_data_variables),
        )
        model_conf = await asyncio.to_thread(ModelConfigConverter.convert, app_config)
        prompt_messages, stop = _build_completion_prompt_messages(
            app_config=app_config,
            model_conf=model_conf,
            inputs=source_message.inputs,
            query=source_message.query,
        )
        message = await _create_completion_message(
            context=context,
            query=source_message.query,
            inputs=source_message.inputs,
        )
        task_id = str(uuid.uuid4())

        if not streaming:
            llm_result = await asyncio.to_thread(
                cls._invoke_blocking,
                model_conf,
                prompt_messages,
                stop,
            )
            await _save_message_result(
                message_id=message.id,
                answer=llm_result.message.get_text_content(),
                usage=llm_result.usage,
            )
            return CompletionAppBlockingResponse(
                task_id=task_id,
                data=CompletionAppBlockingResponse.Data(
                    id=message.id,
                    mode="completion",
                    message_id=message.id,
                    answer=llm_result.message.get_text_content(),
                    metadata={"usage": llm_result.usage.model_dump(mode="json")},
                    created_at=_timestamp(message.created_at),
                ),
            )

        return cls._stream_completion(
            task_id=task_id,
            message=message,
            model_conf=model_conf,
            prompt_messages=prompt_messages,
            stop=stop,
        )

    @classmethod
    async def run_chat(
        cls,
        *,
        context: WebappContext,
        inputs: dict[str, Any],
        query: str,
        files: list[dict[str, Any]] | None,
        conversation_id: str | None,
        parent_message_id: str | None,
        streaming: bool,
    ) -> ChatbotAppBlockingResponse | CompletionAppBlockingResponse | AsyncIterator[str] | Mapping[str, Any] | Iterator[str]:
        if context.app.mode == context.app.mode.CHAT:
            app_config = _build_chat_config(context)
            _ensure_supported_features(
                files=files,
                dataset_enabled=bool(app_config.dataset and app_config.dataset.dataset_ids),
                external_tools_enabled=bool(app_config.external_data_variables),
            )
            model_conf = await asyncio.to_thread(ModelConfigConverter.convert, app_config)
            conversation, message = await _create_chat_records(
                context=context,
                app_model_config_id=app_config.app_model_config_id,
                query=query,
                inputs=inputs,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                introduction=app_config.additional_features.opening_statement if app_config.additional_features else None,
            )
            history_messages = await _load_chat_history(conversation_id=conversation.id)
            prompt_messages, stop = _build_chat_prompt_messages(
                app_config=app_config,
                model_conf=model_conf,
                inputs=inputs,
                query=query,
                history_messages=history_messages,
            )
            task_id = str(uuid.uuid4())

            if not streaming:
                llm_result = await asyncio.to_thread(
                    cls._invoke_blocking,
                    model_conf,
                    prompt_messages,
                    stop,
                )
                await _save_message_result(
                    message_id=message.id,
                    answer=llm_result.message.get_text_content(),
                    usage=llm_result.usage,
                )
                return ChatbotAppBlockingResponse(
                    task_id=task_id,
                    data=ChatbotAppBlockingResponse.Data(
                        id=message.id,
                        mode="chat",
                        conversation_id=conversation.id,
                        message_id=message.id,
                        answer=llm_result.message.get_text_content(),
                        metadata={"usage": llm_result.usage.model_dump(mode="json")},
                        created_at=_timestamp(message.created_at),
                    ),
                )

            return cls._stream_chat(
                task_id=task_id,
                conversation=conversation,
                message=message,
                model_conf=model_conf,
                prompt_messages=prompt_messages,
                stop=stop,
            )

        if context.app.mode in {context.app.mode.ADVANCED_CHAT, context.app.mode.AGENT_CHAT}:
            compatibility_args: _CompatibilityGenerationArgs = {
                "inputs": inputs,
                "query": query,
                "auto_generate_name": False,
            }
            if files:
                compatibility_args["files"] = files
            if conversation_id is not None:
                compatibility_args["conversation_id"] = conversation_id
            if parent_message_id is not None:
                compatibility_args["parent_message_id"] = parent_message_id
            return await _run_compat_public_generation(
                context=context,
                args=compatibility_args,
                streaming=streaming,
            )

        raise service_unavailable(
            "generation_backend_unavailable",
            "Async-native chat generation is only ported for chat apps so far.",
        )

    @classmethod
    async def run_workflow(
        cls,
        *,
        context: WebappContext,
        inputs: dict[str, Any],
        files: list[dict[str, Any]] | None,
        streaming: bool,
    ) -> Mapping[str, Any] | Iterator[str]:
        compatibility_args: _CompatibilityGenerationArgs = {
            "inputs": inputs,
        }
        if files:
            compatibility_args["files"] = files
        return await _run_compat_public_generation(
            context=context,
            args=compatibility_args,
            streaming=streaming,
        )

    @staticmethod
    def _invoke_blocking(
        model_conf: ModelConfigWithCredentialsEntity,
        prompt_messages: list[PromptMessage],
        stop: list[str] | None,
    ) -> LLMResult:
        model_instance = ModelInstance(
            provider_model_bundle=model_conf.provider_model_bundle,
            model=model_conf.model,
        )
        result = model_instance.invoke_llm(
            prompt_messages=prompt_messages,
            model_parameters=model_conf.parameters,
            stop=stop,
            stream=False,
        )
        return cast(LLMResult, result)

    @classmethod
    async def _stream_completion(
        cls,
        *,
        task_id: str,
        message: Message,
        model_conf: ModelConfigWithCredentialsEntity,
        prompt_messages: list[PromptMessage],
        stop: list[str] | None,
    ) -> AsyncIterator[str]:
        model_instance = ModelInstance(
            provider_model_bundle=model_conf.provider_model_bundle,
            model=model_conf.model,
        )
        iterator = cast(
            Iterator[LLMResultChunk],
            model_instance.invoke_llm(
                prompt_messages=prompt_messages,
                model_parameters=model_conf.parameters,
                stop=stop,
                stream=True,
            ),
        )
        answer_parts: list[str] = []
        usage: LLMUsage | None = None
        while True:
            chunk = await _next_chunk(iterator)
            if chunk is None:
                break
            delta_text = chunk.delta.message.get_text_content()
            if delta_text:
                answer_parts.append(delta_text)
                payload = CompletionAppStreamResponse(
                    message_id=message.id,
                    created_at=_timestamp(message.created_at),
                    stream_response=MessageStreamResponse(
                        task_id=task_id,
                        id=message.id,
                        answer=delta_text,
                    ),
                ).model_dump(mode="json")
                yield _encode_sse(payload)
            if chunk.delta.usage is not None:
                usage = chunk.delta.usage

        answer = "".join(answer_parts)
        await _save_message_result(message_id=message.id, answer=answer, usage=usage)
        end_payload = CompletionAppStreamResponse(
            message_id=message.id,
            created_at=_timestamp(message.created_at),
            stream_response=MessageEndStreamResponse(
                task_id=task_id,
                id=message.id,
                metadata={"usage": usage.model_dump(mode="json")} if usage else {},
            ),
        ).model_dump(mode="json")
        yield _encode_sse(end_payload)

    @classmethod
    async def _stream_chat(
        cls,
        *,
        task_id: str,
        conversation: Conversation,
        message: Message,
        model_conf: ModelConfigWithCredentialsEntity,
        prompt_messages: list[PromptMessage],
        stop: list[str] | None,
    ) -> AsyncIterator[str]:
        model_instance = ModelInstance(
            provider_model_bundle=model_conf.provider_model_bundle,
            model=model_conf.model,
        )
        iterator = cast(
            Iterator[LLMResultChunk],
            model_instance.invoke_llm(
                prompt_messages=prompt_messages,
                model_parameters=model_conf.parameters,
                stop=stop,
                stream=True,
            ),
        )
        answer_parts: list[str] = []
        usage: LLMUsage | None = None
        while True:
            chunk = await _next_chunk(iterator)
            if chunk is None:
                break
            delta_text = chunk.delta.message.get_text_content()
            if delta_text:
                answer_parts.append(delta_text)
                payload = ChatbotAppStreamResponse(
                    conversation_id=conversation.id,
                    message_id=message.id,
                    created_at=_timestamp(message.created_at),
                    stream_response=MessageStreamResponse(
                        task_id=task_id,
                        id=message.id,
                        answer=delta_text,
                    ),
                ).model_dump(mode="json")
                yield _encode_sse(payload)
            if chunk.delta.usage is not None:
                usage = chunk.delta.usage

        answer = "".join(answer_parts)
        await _save_message_result(message_id=message.id, answer=answer, usage=usage)
        end_payload = ChatbotAppStreamResponse(
            conversation_id=conversation.id,
            message_id=message.id,
            created_at=_timestamp(message.created_at),
            stream_response=MessageEndStreamResponse(
                task_id=task_id,
                id=message.id,
                metadata={"usage": usage.model_dump(mode="json")} if usage else {},
            ),
        ).model_dump(mode="json")
        yield _encode_sse(end_payload)
