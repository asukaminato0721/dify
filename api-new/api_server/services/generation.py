"""Public generation services for the FastAPI runtime.

Completion and plain-chat requests are handled natively in this module.
Workflow, advanced-chat, and agent-chat now execute through direct runner
paths that avoid the broader Flask controller bridge.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import AsyncIterator, Generator, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import contexts
from api_server.errors import bad_request, forbidden, not_found, service_unavailable
from api_server.models.app import (
    App as FastAPIApp,
)
from api_server.models.app import (
    AppMode,
    AppModelConfig,
    Conversation,
    Message,
    MessageAgentThought,
    MessageFile,
)
from api_server.models.app import (
    EndUser as FastAPIEndUser,
)
from api_server.models.app import (
    UploadFile as FastAPIUploadFile,
)
from api_server.models.app import (
    Workflow as FastAPIWorkflow,
)
from api_server.services.webapp_context import WebappContext
from api_server.models.workflow import WorkflowAppLog, WorkflowAppLogCreatedFrom
from configs import dify_config
from core.app.app_config.base_app_config_manager import BaseAppConfigManager
from core.app.app_config.common.sensitive_word_avoidance.manager import SensitiveWordAvoidanceConfigManager
from core.app.app_config.easy_ui_based_app.dataset.manager import DatasetConfigManager
from core.app.app_config.easy_ui_based_app.model_config.converter import ModelConfigConverter
from core.app.app_config.easy_ui_based_app.model_config.manager import ModelConfigManager
from core.app.app_config.easy_ui_based_app.prompt_template.manager import PromptTemplateConfigManager
from core.app.app_config.easy_ui_based_app.variables.manager import BasicVariablesConfigManager
from core.app.app_config.features.file_upload.manager import FileUploadConfigManager
from core.app.apps.advanced_chat.app_config_manager import AdvancedChatAppConfigManager
from core.app.apps.advanced_chat.app_runner import AdvancedChatAppRunner
from core.app.apps.advanced_chat.generate_response_converter import AdvancedChatAppGenerateResponseConverter
from core.app.apps.advanced_chat.generate_task_pipeline import (
    AdvancedChatMessagePersistence,
    AdvancedChatAppGenerateTaskPipeline,
    ConversationSnapshot,
    MessageSnapshot,
    WorkflowSnapshot,
)
from core.app.apps.agent_chat.app_config_manager import AgentChatAppConfigManager
from core.app.apps.agent_chat.app_runner import AgentChatAppRunner
from core.app.apps.agent_chat.generate_response_converter import AgentChatAppGenerateResponseConverter
from core.app.apps.base_app_generator import BaseAppGenerator
from core.app.apps.base_app_queue_manager import PublishFrom
from core.app.apps.chat.app_generator import ChatAppGenerator
from core.app.apps.chat.app_config_manager import ChatAppConfig
from core.app.apps.completion.app_config_manager import CompletionAppConfig
from core.app.apps.completion.app_generator import CompletionAppGenerator
from core.app.apps.exc import GenerateTaskStoppedError
from core.app.apps.message_based_app_queue_manager import MessageBasedAppQueueManager
from core.app.apps.workflow.app_config_manager import WorkflowAppConfigManager
from core.app.apps.workflow.app_queue_manager import WorkflowAppQueueManager
from core.app.apps.workflow.app_runner import WorkflowAppRunner
from core.app.apps.workflow.generate_response_converter import WorkflowAppGenerateResponseConverter
from core.app.apps.workflow.generate_task_pipeline import WorkflowAppGenerateTaskPipeline
from core.app.entities.app_invoke_entities import (
    AdvancedChatAppGenerateEntity,
    AgentChatAppGenerateEntity,
    InvokeFrom,
    ModelConfigWithCredentialsEntity,
    WorkflowAppGenerateEntity,
)
from core.app.entities.task_entities import (
    ChatbotAppBlockingResponse,
    ChatbotAppStreamResponse,
    CompletionAppBlockingResponse,
    CompletionAppStreamResponse,
    MessageEndStreamResponse,
    MessageStreamResponse,
)
from core.app.layers.pause_state_persist_layer import PauseStateLayerConfig, PauseStatePersistenceLayer
from core.app.task_pipeline.easy_ui_based_generate_task_pipeline import EasyUIBasedGenerateTaskPipeline
from core.app.task_pipeline.message_file_utils import MessageFileInfoDict, prepare_file_dict
from core.db.session_factory import session_factory as configured_sync_session_factory
from core.model_manager import ModelInstance
from core.ops.ops_trace_manager import TraceQueueManager
from core.prompt.advanced_prompt_transform import AdvancedPromptTransform
from core.prompt.entities.advanced_prompt_entities import CompletionModelPromptTemplate, MemoryConfig
from core.prompt.simple_prompt_transform import SimplePromptTransform
from core.prompt.utils.extract_thread_messages import extract_thread_messages
from core.prompt.utils.prompt_template_parser import PromptTemplateParser
from core.repositories import DifyCoreRepositoryFactory
from core.repositories.factory import WorkflowExecutionRepository, WorkflowNodeExecutionRepository
from core.workflow.file_reference import resolve_file_record_id
from extensions.ext_database import db
from factories import file_factory
from graphon.file import FileTransferMethod
from graphon.model_runtime.entities.llm_entities import LLMResult, LLMResultChunk, LLMUsage
from graphon.model_runtime.entities.message_entities import (
    AssistantPromptMessage,
    PromptMessage,
    UserPromptMessage,
)
from graphon.model_runtime.errors.invoke import InvokeAuthorizationError
from graphon.prompt_entities import ChatModelMessage
from graphon.variable_loader import DUMMY_VARIABLE_LOADER
from libs.datetime_utils import naive_utc_now
from libs.orjson import orjson_dumps
from models.enums import ConversationFromSource, CreatorUserRole, MessageFileBelongsTo, WorkflowRunTriggeredFrom
from models.model import AppModelConfigDict
from models.workflow import WorkflowNodeExecutionTriggeredFrom


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


def _set_runtime_cache(target: object, name: str, value: object) -> None:
    """Attach ad-hoc cache state to ORM rows that are later consumed by legacy sync runners."""

    setattr(target, name, value)


def _resolve_workflow_app_log_created_from(invoke_from: InvokeFrom) -> WorkflowAppLogCreatedFrom | None:
    match invoke_from:
        case InvokeFrom.SERVICE_API:
            return WorkflowAppLogCreatedFrom.SERVICE_API
        case InvokeFrom.EXPLORE:
            return WorkflowAppLogCreatedFrom.INSTALLED_APP
        case InvokeFrom.WEB_APP:
            return WorkflowAppLogCreatedFrom.WEB_APP
        case InvokeFrom.DEBUGGER | InvokeFrom.TRIGGER | InvokeFrom.PUBLISHED_PIPELINE | InvokeFrom.VALIDATION:
            return None


async def _save_workflow_app_log_async(
    *,
    application_generate_entity: WorkflowAppGenerateEntity,
    workflow: FastAPIWorkflow,
    created_by_role: CreatorUserRole,
    created_by: str,
) -> None:
    """Persist the workflow-app log on the async request path before runner startup."""

    created_from = _resolve_workflow_app_log_created_from(application_generate_entity.invoke_from)
    if created_from is None:
        return

    async with db.session_context() as session:
        session.add(
            WorkflowAppLog(
                tenant_id=application_generate_entity.app_config.tenant_id,
                app_id=application_generate_entity.app_config.app_id,
                workflow_id=workflow.id,
                workflow_run_id=application_generate_entity.workflow_execution_id,
                created_from=created_from,
                created_by_role=created_by_role,
                created_by=created_by,
            )
        )
        await session.flush()
        await session.commit()


@dataclass(frozen=True, slots=True)
class _HistoryMessage:
    id: str
    query: str
    answer: str
    parent_message_id: str | None


@dataclass(frozen=True, slots=True)
class _PreparedWorkflowRun:
    app_model: FastAPIApp
    workflow: FastAPIWorkflow
    end_user: FastAPIEndUser
    application_generate_entity: WorkflowAppGenerateEntity


@dataclass(frozen=True, slots=True)
class _PreparedAdvancedChatRun:
    app_model: FastAPIApp
    workflow: FastAPIWorkflow
    end_user: FastAPIEndUser
    conversation: Conversation
    message: Message
    application_generate_entity: AdvancedChatAppGenerateEntity
    dialogue_count: int


@dataclass(frozen=True, slots=True)
class _PreparedAgentChatRun:
    app_model: FastAPIApp
    end_user: FastAPIEndUser
    conversation: Conversation
    message: Message
    application_generate_entity: AgentChatAppGenerateEntity


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

    def get_history_prompt_messages(
        self, *, max_token_limit: int = 2000, message_limit: int | None = None
    ) -> list[PromptMessage]:
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
    app_mode = AppMode(str(context.app.mode))
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
    app_mode = AppMode(str(context.app.mode))
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


def _ensure_supported_features(
    *, files: list[dict[str, Any]] | None, dataset_enabled: bool, external_tools_enabled: bool
) -> None:
    _ = (files, dataset_enabled, external_tools_enabled)


def _prepare_workflow_generation_entity(
    *,
    app_model: FastAPIApp,
    workflow: FastAPIWorkflow,
    end_user: FastAPIEndUser,
    inputs: dict[str, Any],
    files: list[dict[str, Any]] | None,
    streaming: bool,
) -> WorkflowAppGenerateEntity:
    """Build the workflow generate entity without touching Flask globals."""

    base_generator = BaseAppGenerator()
    file_extra_config = FileUploadConfigManager.convert(workflow.features_dict, is_vision=False)

    with base_generator._bind_file_access_scope(
        tenant_id=app_model.tenant_id,
        user=end_user,
        invoke_from=InvokeFrom.WEB_APP,
    ):
        file_objects = file_factory.build_from_mappings(
            mappings=files or [],
            tenant_id=app_model.tenant_id,
            config=file_extra_config,
            access_controller=base_generator._file_access_controller,
        )
        app_config = WorkflowAppConfigManager.get_app_config(app_model=app_model, workflow=workflow)
        prepared_inputs = base_generator._prepare_user_inputs(
            user_inputs=inputs,
            variables=app_config.variables,
            tenant_id=app_model.tenant_id,
        )

    trace_manager = TraceQueueManager(app_id=app_model.id, user_id=end_user.session_id)
    return WorkflowAppGenerateEntity(
        task_id=str(uuid.uuid4()),
        app_config=app_config,
        file_upload_config=file_extra_config,
        inputs=prepared_inputs,
        files=list(file_objects),
        user_id=end_user.id,
        stream=streaming,
        invoke_from=InvokeFrom.WEB_APP,
        extras={},
        trace_manager=trace_manager,
        workflow_execution_id=str(uuid.uuid4()),
    )


def _run_workflow_runner(
    *,
    application_generate_entity: WorkflowAppGenerateEntity,
    workflow: FastAPIWorkflow,
    end_user: FastAPIEndUser,
    queue_manager: WorkflowAppQueueManager,
    workflow_execution_repository: Any,
    workflow_node_execution_repository: Any,
    pause_state_config: PauseStateLayerConfig,
) -> None:
    """Execute the workflow runner and push translated failures into the queue."""

    contexts.plugin_tool_providers.set({})
    contexts.plugin_tool_providers_lock.set(threading.Lock())

    runner = WorkflowAppRunner(
        application_generate_entity=application_generate_entity,
        queue_manager=queue_manager,
        variable_loader=DUMMY_VARIABLE_LOADER,
        workflow=workflow,
        system_user_id=end_user.session_id,
        workflow_execution_repository=workflow_execution_repository,
        workflow_node_execution_repository=workflow_node_execution_repository,
        graph_engine_layers=(
            PauseStatePersistenceLayer(
                session_factory=pause_state_config.session_factory,
                generate_entity=application_generate_entity,
                state_owner_user_id=pause_state_config.state_owner_user_id,
            ),
        ),
        graph_runtime_state=None,
    )

    try:
        runner.run()
    except GenerateTaskStoppedError:
        return
    except InvokeAuthorizationError:
        queue_manager.publish_error(
            InvokeAuthorizationError("Incorrect API key provided"), PublishFrom.APPLICATION_MANAGER
        )
    except ValidationError as exc:
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)
    except ValueError as exc:
        if dify_config.DEBUG:
            pass
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)
    except Exception as exc:
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)


def _prepare_advanced_chat_generation_entity(
    *,
    app_model: FastAPIApp,
    workflow: FastAPIWorkflow,
    end_user: FastAPIEndUser,
    inputs: dict[str, Any],
    query: str,
    files: list[dict[str, Any]] | None,
    parent_message_id: str | None,
    auto_generate_name: bool,
    streaming: bool,
) -> AdvancedChatAppGenerateEntity:
    """Build the advanced-chat generate entity without Flask globals."""

    base_generator = BaseAppGenerator()
    file_extra_config = FileUploadConfigManager.convert(workflow.features_dict, is_vision=False)

    with base_generator._bind_file_access_scope(
        tenant_id=app_model.tenant_id,
        user=end_user,
        invoke_from=InvokeFrom.WEB_APP,
    ):
        file_objects = file_factory.build_from_mappings(
            mappings=files or [],
            tenant_id=app_model.tenant_id,
            config=file_extra_config,
            access_controller=base_generator._file_access_controller,
        )
        app_config = AdvancedChatAppConfigManager.get_app_config(app_model=app_model, workflow=workflow)
        prepared_inputs = base_generator._prepare_user_inputs(
            user_inputs=inputs,
            variables=app_config.variables,
            tenant_id=app_model.tenant_id,
        )

    trace_manager = TraceQueueManager(app_id=app_model.id, user_id=end_user.session_id)
    return AdvancedChatAppGenerateEntity(
        task_id=str(uuid.uuid4()),
        app_config=app_config,
        file_upload_config=file_extra_config,
        conversation_id=None,
        inputs=prepared_inputs,
        query=query.replace("\x00", ""),
        files=list(file_objects),
        parent_message_id=parent_message_id,
        user_id=end_user.id,
        stream=streaming,
        invoke_from=InvokeFrom.WEB_APP,
        extras={"auto_generate_conversation_name": auto_generate_name},
        trace_manager=trace_manager,
        workflow_run_id=str(uuid.uuid4()),
    )


def _prepare_agent_chat_generation_entity(
    *,
    app_model: FastAPIApp,
    app_model_config: AppModelConfig,
    end_user: FastAPIEndUser,
    conversation: Conversation | None,
    inputs: dict[str, Any],
    query: str,
    files: list[dict[str, Any]] | None,
    parent_message_id: str | None,
    auto_generate_name: bool,
    streaming: bool,
) -> AgentChatAppGenerateEntity:
    """Build the agent-chat generate entity without Flask controller glue."""

    base_generator = BaseAppGenerator()
    file_extra_config = FileUploadConfigManager.convert(app_model_config.to_dict())

    with base_generator._bind_file_access_scope(
        tenant_id=app_model.tenant_id,
        user=end_user,
        invoke_from=InvokeFrom.WEB_APP,
    ):
        file_objects = file_factory.build_from_mappings(
            mappings=files or [],
            tenant_id=app_model.tenant_id,
            config=file_extra_config,
            access_controller=base_generator._file_access_controller,
        )
        app_config = AgentChatAppConfigManager.get_app_config(
            app_model=app_model,
            app_model_config=app_model_config,
            conversation=conversation,
        )
        prepared_inputs = base_generator._prepare_user_inputs(
            user_inputs=inputs,
            variables=app_config.variables,
            tenant_id=app_model.tenant_id,
        )

    trace_manager = TraceQueueManager(app_id=app_model.id, user_id=end_user.session_id)
    return AgentChatAppGenerateEntity(
        task_id=str(uuid.uuid4()),
        app_config=app_config,
        model_conf=ModelConfigConverter.convert(app_config),
        file_upload_config=file_extra_config,
        conversation_id=conversation.id if conversation else None,
        inputs=prepared_inputs,
        query=query.replace("\x00", ""),
        files=list(file_objects),
        parent_message_id=parent_message_id,
        user_id=end_user.id,
        stream=streaming,
        invoke_from=InvokeFrom.WEB_APP,
        extras={"auto_generate_conversation_name": auto_generate_name},
        call_depth=0,
        trace_manager=trace_manager,
    )


def _render_message_based_conversation_introduction(
    application_generate_entity: AgentChatAppGenerateEntity,
) -> str:
    """Render the opening statement against available inputs for new conversations."""

    app_config = application_generate_entity.app_config
    introduction = app_config.additional_features.opening_statement if app_config.additional_features else None
    if introduction:
        try:
            inputs = application_generate_entity.inputs
            prompt_template = PromptTemplateParser(template=introduction)
            prompt_inputs = {key: inputs[key] for key in prompt_template.variable_keys if key in inputs}
            introduction = prompt_template.format(prompt_inputs)
        except KeyError:
            pass
    return introduction or ""


async def _load_owned_fastapi_conversation(
    *,
    session: AsyncSession,
    app_id: str,
    end_user_id: str,
    conversation_id: str,
) -> Conversation:
    """Return an existing FastAPI public conversation only when it belongs to the caller."""

    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.app_id == app_id,
            Conversation.from_source == ConversationFromSource.API.value,
            Conversation.from_end_user_id == end_user_id,
            Conversation.is_deleted.is_(False),
        )
    )
    if conversation is None:
        raise bad_request("conversation_not_exists", "Conversation Not Exists.")
    return conversation


async def _seed_message_file_caches_async(
    *,
    session: AsyncSession,
    conversation: Conversation,
    message: Message,
    message_files: list[MessageFile],
) -> None:
    """Prime message file caches so legacy sync runners avoid reopening sessions on the active FastAPI path."""

    user_files = [
        message_file
        for message_file in message_files
        if message_file.belongs_to in {None, MessageFileBelongsTo.USER.value}
    ]
    assistant_files = [
        message_file
        for message_file in message_files
        if message_file.belongs_to == MessageFileBelongsTo.ASSISTANT.value
    ]
    upload_file_ids = list(
        dict.fromkeys(
            message_file.upload_file_id
            for message_file in message_files
            if message_file.transfer_method == FileTransferMethod.LOCAL_FILE and message_file.upload_file_id
        )
    )
    upload_files_map: dict[str, FastAPIUploadFile] = {}
    if upload_file_ids:
        upload_files = (
            await session.scalars(select(FastAPIUploadFile).where(FastAPIUploadFile.id.in_(upload_file_ids)))
        ).all()
        upload_files_map = {upload_file.id: upload_file for upload_file in upload_files}

    prefetched_message_end_files = [
        prepare_file_dict(message_file, cast(dict[str, Any], upload_files_map)) for message_file in message_files
    ]
    _set_runtime_cache(message, "_cached_conversation", conversation)
    _set_runtime_cache(message, "_cached_user_message_files", user_files)
    _set_runtime_cache(message, "_cached_assistant_message_files", assistant_files)
    _set_runtime_cache(
        message,
        "_cached_message_end_files",
        cast(list[MessageFileInfoDict], prefetched_message_end_files),
    )


async def _init_agent_chat_records_async(
    *,
    session: AsyncSession,
    application_generate_entity: AgentChatAppGenerateEntity,
    end_user: FastAPIEndUser,
    conversation: Conversation | None,
) -> tuple[Conversation, Message]:
    """Persist conversation/message rows for public agent-chat generation on `AsyncSession`."""

    app_config = application_generate_entity.app_config
    created_new_conversation = conversation is None
    query = application_generate_entity.query or "New conversation"
    conversation_name = (query[:20] + "…") if len(query) > 20 else query

    override_model_configs: dict[str, Any] | None = None
    if app_config.app_model_config_from == app_config.app_model_config_from.ARGS:
        override_model_configs = cast(dict[str, Any], app_config.app_model_config_dict)

    if conversation is None:
        conversation = Conversation(
            app_id=app_config.app_id,
            app_model_config_id=app_config.app_model_config_id,
            model_provider=application_generate_entity.model_conf.provider,
            model_id=application_generate_entity.model_conf.model,
            override_model_configs=json.dumps(override_model_configs) if override_model_configs else None,
            mode=app_config.app_mode.value,
            name=conversation_name,
            inputs=application_generate_entity.inputs,
            introduction=_render_message_based_conversation_introduction(application_generate_entity),
            system_instruction="",
            system_instruction_tokens=0,
            status="normal",
            invoke_from=application_generate_entity.invoke_from.value,
            from_source=ConversationFromSource.API.value,
            from_end_user_id=end_user.id,
            from_account_id=None,
        )
        session.add(conversation)
        await session.flush()
    else:
        conversation.updated_at = naive_utc_now()

    message = Message(
        app_id=app_config.app_id,
        model_provider=application_generate_entity.model_conf.provider,
        model_id=application_generate_entity.model_conf.model,
        override_model_configs=json.dumps(override_model_configs) if override_model_configs else None,
        conversation_id=conversation.id,
        inputs=application_generate_entity.inputs,
        query=application_generate_entity.query,
        message={},
        message_tokens=0,
        message_unit_price=0,
        message_price_unit=0,
        answer="",
        answer_tokens=0,
        answer_unit_price=0,
        answer_price_unit=0,
        parent_message_id=application_generate_entity.parent_message_id,
        provider_response_latency=0,
        total_price=0,
        currency="USD",
        invoke_from=application_generate_entity.invoke_from.value,
        from_source=ConversationFromSource.API.value,
        from_end_user_id=end_user.id,
        from_account_id=None,
        app_mode=app_config.app_mode.value,
    )
    session.add(message)
    await session.flush()

    message_files: list[MessageFile] = []
    for file in application_generate_entity.files:
        message_files.append(
            MessageFile(
                message_id=message.id,
                type=file.type,
                transfer_method=file.transfer_method,
                belongs_to=MessageFileBelongsTo.USER.value,
                url=file.remote_url,
                upload_file_id=resolve_file_record_id(file.reference),
                created_by_role=CreatorUserRole.END_USER.value,
                created_by=end_user.id,
            )
        )
    if message_files:
        session.add_all(message_files)
        await _seed_message_file_caches_async(
            session=session,
            conversation=conversation,
            message=message,
            message_files=message_files,
        )

    await session.commit()
    await session.refresh(conversation)
    await session.refresh(message)
    application_generate_entity.conversation_id = conversation.id
    application_generate_entity.is_new_conversation = created_new_conversation
    return conversation, message


async def _init_advanced_chat_records_async(
    *,
    session: AsyncSession,
    application_generate_entity: AdvancedChatAppGenerateEntity,
    end_user: FastAPIEndUser,
    conversation: Conversation | None,
) -> tuple[Conversation, Message]:
    """Persist conversation/message rows for public advanced-chat generation on `AsyncSession`."""

    app_config = application_generate_entity.app_config
    created_new_conversation = conversation is None
    query = application_generate_entity.query or "New conversation"
    conversation_name = (query[:20] + "…") if len(query) > 20 else query

    if conversation is None:
        conversation = Conversation(
            app_id=app_config.app_id,
            app_model_config_id=None,
            model_provider=None,
            model_id=None,
            override_model_configs=None,
            mode=app_config.app_mode.value,
            name=conversation_name,
            inputs=application_generate_entity.inputs,
            introduction=app_config.additional_features.opening_statement if app_config.additional_features else None,
            system_instruction="",
            system_instruction_tokens=0,
            status="normal",
            invoke_from=application_generate_entity.invoke_from.value,
            from_source=ConversationFromSource.API.value,
            from_end_user_id=end_user.id,
            from_account_id=None,
        )
        session.add(conversation)
        await session.flush()
    else:
        conversation.updated_at = naive_utc_now()

    message = Message(
        app_id=app_config.app_id,
        model_provider=None,
        model_id=None,
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs=application_generate_entity.inputs,
        query=application_generate_entity.query,
        message={},
        message_tokens=0,
        message_unit_price=0,
        message_price_unit=0,
        answer="",
        answer_tokens=0,
        answer_unit_price=0,
        answer_price_unit=0,
        parent_message_id=application_generate_entity.parent_message_id,
        provider_response_latency=0,
        total_price=0,
        currency="USD",
        invoke_from=application_generate_entity.invoke_from.value,
        from_source=ConversationFromSource.API.value,
        from_end_user_id=end_user.id,
        from_account_id=None,
        app_mode=app_config.app_mode.value,
    )
    session.add(message)
    await session.flush()

    message_files: list[MessageFile] = []
    for file in application_generate_entity.files:
        message_files.append(
            MessageFile(
                message_id=message.id,
                type=file.type,
                transfer_method=file.transfer_method,
                belongs_to=MessageFileBelongsTo.USER.value,
                url=file.remote_url,
                upload_file_id=resolve_file_record_id(file.reference),
                created_by_role=CreatorUserRole.END_USER.value,
                created_by=end_user.id,
            )
        )
    if message_files:
        session.add_all(message_files)
        await _seed_message_file_caches_async(
            session=session,
            conversation=conversation,
            message=message,
            message_files=message_files,
        )

    await session.commit()
    await session.refresh(conversation)
    await session.refresh(message)
    application_generate_entity.conversation_id = conversation.id
    application_generate_entity.is_new_conversation = created_new_conversation
    return conversation, message


async def _load_thread_messages_length_async(*, conversation_id: str, message_model: type[Message]) -> int:
    """Mirror legacy thread counting on `AsyncSession` before entering sync runners."""

    async with db.session_context() as session:
        messages = (
            await session.scalars(
                select(message_model)
                .where(message_model.conversation_id == conversation_id)
                .order_by(message_model.created_at.desc())
            )
        ).all()
    thread_messages = extract_thread_messages(messages)
    if thread_messages and not thread_messages[0].answer:
        thread_messages.pop(0)
    return len(thread_messages)


async def _prefetch_agent_chat_memory_async(
    *,
    session: AsyncSession,
    conversation: Conversation,
    app_model: FastAPIApp,
    app_model_config: AppModelConfig,
) -> None:
    """Attach request-stage agent memory state so sync runners avoid reopening sessions on the active path."""

    _set_runtime_cache(conversation, "_cached_app", app_model)
    _set_runtime_cache(conversation, "_cached_app_model_config", app_model_config)

    history_messages = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(500)
        )
    ).all()
    _set_runtime_cache(conversation, "_cached_history_messages", list(history_messages))

    if not history_messages:
        return

    message_ids = [message.id for message in history_messages]
    history_files = (
        await session.scalars(select(MessageFile).where(MessageFile.message_id.in_(message_ids)))
    ).all()
    agent_thoughts = (
        await session.scalars(
            select(MessageAgentThought)
            .where(MessageAgentThought.message_id.in_(message_ids))
            .order_by(MessageAgentThought.message_id.asc(), MessageAgentThought.position.asc())
        )
    ).all()

    files_by_message_id: dict[str, list[MessageFile]] = {message_id: [] for message_id in message_ids}
    for message_file in history_files:
        files_by_message_id.setdefault(message_file.message_id, []).append(message_file)

    upload_file_ids = list(
        dict.fromkeys(
            message_file.upload_file_id
            for message_file in history_files
            if message_file.transfer_method == "local_file" and message_file.upload_file_id
        )
    )
    upload_files_map: dict[str, FastAPIUploadFile] = {}
    if upload_file_ids:
        upload_files = (
            await session.scalars(select(FastAPIUploadFile).where(FastAPIUploadFile.id.in_(upload_file_ids)))
        ).all()
        upload_files_map = {upload_file.id: upload_file for upload_file in upload_files}

    thoughts_by_message_id: dict[str, list[MessageAgentThought]] = {message_id: [] for message_id in message_ids}
    for agent_thought in agent_thoughts:
        thoughts_by_message_id.setdefault(agent_thought.message_id, []).append(agent_thought)

    for history_message in history_messages:
        message_files = files_by_message_id.get(history_message.id, [])
        user_files = [
            message_file
            for message_file in message_files
            if message_file.belongs_to in {None, MessageFileBelongsTo.USER.value}
        ]
        assistant_files = [
            message_file
            for message_file in message_files
            if message_file.belongs_to == MessageFileBelongsTo.ASSISTANT.value
        ]
        cached_thoughts = thoughts_by_message_id.get(history_message.id, [])
        prefetched_message_end_files = [
            prepare_file_dict(message_file, cast(dict[str, Any], upload_files_map)) for message_file in message_files
        ]
        _set_runtime_cache(history_message, "_cached_user_message_files", user_files)
        _set_runtime_cache(history_message, "_cached_assistant_message_files", assistant_files)
        _set_runtime_cache(history_message, "_cached_app_model_config", app_model_config)
        _set_runtime_cache(history_message, "_cached_conversation", conversation)
        _set_runtime_cache(history_message, "_cached_agent_thoughts", cached_thoughts)
        _set_runtime_cache(history_message, "_cached_agent_thought_count", len(cached_thoughts))
        _set_runtime_cache(
            history_message,
            "_cached_message_end_files",
            cast(list[MessageFileInfoDict], prefetched_message_end_files),
        )


def _run_advanced_chat_runner(
    *,
    application_generate_entity: AdvancedChatAppGenerateEntity,
    workflow: FastAPIWorkflow,
    app_model: FastAPIApp,
    end_user: FastAPIEndUser,
    conversation: Conversation,
    message: Message,
    dialogue_count: int,
    queue_manager: MessageBasedAppQueueManager,
    workflow_execution_repository: WorkflowExecutionRepository,
    workflow_node_execution_repository: WorkflowNodeExecutionRepository,
    pause_state_config: PauseStateLayerConfig,
) -> None:
    """Execute the advanced-chat runner without the Flask controller bridge."""

    contexts.plugin_tool_providers.set({})
    contexts.plugin_tool_providers_lock.set(threading.Lock())

    runner = AdvancedChatAppRunner(
        application_generate_entity=application_generate_entity,
        queue_manager=queue_manager,
        conversation=conversation,
        message=message,
        dialogue_count=dialogue_count,
        variable_loader=DUMMY_VARIABLE_LOADER,
        workflow=workflow,
        system_user_id=end_user.session_id,
        app=app_model,
        workflow_execution_repository=workflow_execution_repository,
        workflow_node_execution_repository=workflow_node_execution_repository,
        graph_engine_layers=(
            PauseStatePersistenceLayer(
                session_factory=pause_state_config.session_factory,
                generate_entity=application_generate_entity,
                state_owner_user_id=pause_state_config.state_owner_user_id,
            ),
        ),
        graph_runtime_state=None,
    )

    try:
        asyncio.run(_drain_advanced_chat_runner_async(runner))
    except GenerateTaskStoppedError:
        return
    except InvokeAuthorizationError:
        queue_manager.publish_error(
            InvokeAuthorizationError("Incorrect API key provided"), PublishFrom.APPLICATION_MANAGER
        )
    except ValidationError as exc:
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)
    except ValueError as exc:
        if dify_config.DEBUG:
            pass
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)
    except Exception as exc:
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)


async def _drain_advanced_chat_runner_async(runner: AdvancedChatAppRunner) -> None:
    """Consume the async advanced-chat runner inside a worker thread."""

    async for _ in runner.run_async():
        continue


def _run_agent_chat_runner(
    *,
    application_generate_entity: AgentChatAppGenerateEntity,
    queue_manager: MessageBasedAppQueueManager,
    app_model: FastAPIApp,
    conversation: Conversation,
    message: Message,
) -> None:
    """Execute the agent-chat runner without the Flask controller bridge."""

    runner = AgentChatAppRunner()
    try:
        runner.run(
            application_generate_entity=application_generate_entity,
            queue_manager=queue_manager,
            conversation=conversation,
            message=message,
            app_record=app_model,
        )
    except GenerateTaskStoppedError:
        return
    except InvokeAuthorizationError:
        queue_manager.publish_error(
            InvokeAuthorizationError("Incorrect API key provided"), PublishFrom.APPLICATION_MANAGER
        )
    except ValidationError as exc:
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)
    except ValueError as exc:
        if dify_config.DEBUG:
            pass
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)
    except Exception as exc:
        queue_manager.publish_error(exc, PublishFrom.APPLICATION_MANAGER)


def _start_native_public_advanced_chat(
    *,
    prepared: _PreparedAdvancedChatRun,
    streaming: bool,
) -> Mapping[str, Any] | Iterator[str]:
    """Start advanced-chat after async request-stage loading has completed."""

    app_model = prepared.app_model
    workflow = prepared.workflow
    end_user = prepared.end_user
    conversation = prepared.conversation
    message = prepared.message
    application_generate_entity = prepared.application_generate_entity
    dialogue_count = prepared.dialogue_count
    runtime_session_maker = configured_sync_session_factory.get_session_maker()

    workflow_execution_repository = DifyCoreRepositoryFactory.create_workflow_execution_repository(
        session_factory=runtime_session_maker,
        user=end_user,
        app_id=application_generate_entity.app_config.app_id,
        triggered_from=WorkflowRunTriggeredFrom.APP_RUN,
    )
    workflow_node_execution_repository = DifyCoreRepositoryFactory.create_workflow_node_execution_repository(
        session_factory=runtime_session_maker,
        user=end_user,
        app_id=application_generate_entity.app_config.app_id,
        triggered_from=WorkflowNodeExecutionTriggeredFrom.WORKFLOW_RUN,
    )
    queue_manager = MessageBasedAppQueueManager(
        task_id=application_generate_entity.task_id,
        user_id=end_user.id,
        invoke_from=InvokeFrom.WEB_APP,
        conversation_id=conversation.id,
        app_mode=conversation.mode,
        message_id=message.id,
    )
    pause_state_config = PauseStateLayerConfig(
        session_factory=runtime_session_maker,
        state_owner_user_id=workflow.created_by or end_user.id,
    )

    worker = threading.Thread(
        target=_run_advanced_chat_runner,
        kwargs={
            "application_generate_entity": application_generate_entity,
            "workflow": workflow,
            "app_model": app_model,
            "end_user": end_user,
            "conversation": conversation,
            "message": message,
            "dialogue_count": dialogue_count,
            "queue_manager": queue_manager,
            "workflow_execution_repository": workflow_execution_repository,
            "workflow_node_execution_repository": workflow_node_execution_repository,
            "pause_state_config": pause_state_config,
        },
        daemon=True,
    )
    worker.start()

    response = AdvancedChatAppGenerateTaskPipeline(
        application_generate_entity=application_generate_entity,
        workflow=WorkflowSnapshot.from_workflow(workflow),
        queue_manager=queue_manager,
        conversation=ConversationSnapshot.from_conversation(conversation),
        message=MessageSnapshot.from_message(message),
        user=end_user,
        dialogue_count=dialogue_count,
        stream=streaming,
        draft_var_saver_factory=BaseAppGenerator._get_draft_var_saver_factory(InvokeFrom.WEB_APP, end_user),
        message_persistence=AdvancedChatMessagePersistence(configured_sync_session_factory.get_session_maker()),
    ).process()
    converted = AdvancedChatAppGenerateResponseConverter.convert(response=response, invoke_from=InvokeFrom.WEB_APP)
    return cast(Mapping[str, Any] | Iterator[str], BaseAppGenerator.convert_to_event_stream(converted))


async def _run_native_public_advanced_chat(
    *,
    context: WebappContext,
    inputs: dict[str, Any],
    query: str,
    files: list[dict[str, Any]] | None,
    conversation_id: str | None,
    parent_message_id: str | None,
    auto_generate_name: bool,
    streaming: bool,
) -> Mapping[str, Any] | Iterator[str]:
    prepared = await _prepare_native_public_advanced_chat(
        context=context,
        inputs=inputs,
        query=query,
        files=files,
        conversation_id=conversation_id,
        parent_message_id=parent_message_id,
        auto_generate_name=auto_generate_name,
        streaming=streaming,
    )
    if streaming:
        return _start_native_public_advanced_chat(
            prepared=prepared,
            streaming=True,
        )
    return await asyncio.to_thread(
        _start_native_public_advanced_chat,
        prepared=prepared,
        streaming=False,
    )


async def _prepare_native_public_advanced_chat(
    *,
    context: WebappContext,
    inputs: dict[str, Any],
    query: str,
    files: list[dict[str, Any]] | None,
    conversation_id: str | None,
    parent_message_id: str | None,
    auto_generate_name: bool,
    streaming: bool,
) -> _PreparedAdvancedChatRun:
    """Load and persist advanced-chat request state on `AsyncSession` before entering sync runners."""

    if context.workflow is None:
        raise bad_request("app_unavailable", "App unavailable, please refresh and try again.")

    async with db.session_context() as session:
        app_model = await session.get(FastAPIApp, context.app.id)
        workflow = await session.scalar(
            select(FastAPIWorkflow).where(
                FastAPIWorkflow.id == context.workflow.id,
                FastAPIWorkflow.app_id == context.app.id,
            )
        )
        end_user = await session.get(FastAPIEndUser, context.end_user.id)
        if app_model is None or workflow is None or end_user is None:
            raise bad_request("app_unavailable", "App unavailable, please refresh and try again.")

        conversation = None
        if conversation_id is not None:
            conversation = await _load_owned_fastapi_conversation(
                session=session,
                app_id=app_model.id,
                end_user_id=end_user.id,
                conversation_id=conversation_id,
            )

        application_generate_entity = _prepare_advanced_chat_generation_entity(
            app_model=app_model,
            workflow=workflow,
            end_user=end_user,
            inputs=inputs,
            query=query,
            files=files,
            parent_message_id=parent_message_id,
            auto_generate_name=auto_generate_name,
            streaming=streaming,
        )
        conversation, message = await _init_advanced_chat_records_async(
            session=session,
            application_generate_entity=application_generate_entity,
            end_user=end_user,
            conversation=conversation,
        )

    dialogue_count = await _load_thread_messages_length_async(
        conversation_id=conversation.id,
        message_model=Message,
    ) + 1
    return _PreparedAdvancedChatRun(
        app_model=app_model,
        workflow=workflow,
        end_user=end_user,
        conversation=conversation,
        message=message,
        application_generate_entity=application_generate_entity,
        dialogue_count=dialogue_count,
    )


def _start_native_public_agent_chat(
    *,
    prepared: _PreparedAgentChatRun,
) -> Iterator[str]:
    """Start agent-chat after async request-stage loading has completed."""

    app_model = prepared.app_model
    end_user = prepared.end_user
    conversation = prepared.conversation
    message = prepared.message
    application_generate_entity = prepared.application_generate_entity

    queue_manager = MessageBasedAppQueueManager(
        task_id=application_generate_entity.task_id,
        user_id=end_user.id,
        invoke_from=InvokeFrom.WEB_APP,
        conversation_id=conversation.id,
        app_mode=conversation.mode,
        message_id=message.id,
    )

    worker = threading.Thread(
        target=_run_agent_chat_runner,
        kwargs={
            "application_generate_entity": application_generate_entity,
            "queue_manager": queue_manager,
            "app_model": app_model,
            "conversation": conversation,
            "message": message,
        },
        daemon=True,
    )
    worker.start()

    response = EasyUIBasedGenerateTaskPipeline(
        application_generate_entity=application_generate_entity,
        queue_manager=queue_manager,
        conversation=conversation,
        message=message,
        stream=True,
    ).process()
    converted = AgentChatAppGenerateResponseConverter.convert(response=response, invoke_from=InvokeFrom.WEB_APP)
    return cast(Iterator[str], BaseAppGenerator.convert_to_event_stream(converted))


async def _run_native_public_agent_chat(
    *,
    context: WebappContext,
    inputs: dict[str, Any],
    query: str,
    files: list[dict[str, Any]] | None,
    conversation_id: str | None,
    parent_message_id: str | None,
    auto_generate_name: bool,
) -> Iterator[str]:
    prepared = await _prepare_native_public_agent_chat(
        context=context,
        inputs=inputs,
        query=query,
        files=files,
        conversation_id=conversation_id,
        parent_message_id=parent_message_id,
        auto_generate_name=auto_generate_name,
    )
    return _start_native_public_agent_chat(prepared=prepared)


async def _prepare_native_public_agent_chat(
    *,
    context: WebappContext,
    inputs: dict[str, Any],
    query: str,
    files: list[dict[str, Any]] | None,
    conversation_id: str | None,
    parent_message_id: str | None,
    auto_generate_name: bool,
) -> _PreparedAgentChatRun:
    """Load and persist agent-chat request state on `AsyncSession` before entering sync runners."""

    async with db.session_context() as session:
        app_model = await session.get(FastAPIApp, context.app.id)
        app_model_config = await session.get(AppModelConfig, context.app.app_model_config_id)
        end_user = await session.get(FastAPIEndUser, context.end_user.id)
        if app_model is None or app_model_config is None or end_user is None:
            raise bad_request("app_unavailable", "App unavailable, please refresh and try again.")

        conversation = None
        if conversation_id is not None:
            conversation = await _load_owned_fastapi_conversation(
                session=session,
                app_id=app_model.id,
                end_user_id=end_user.id,
                conversation_id=conversation_id,
            )

        application_generate_entity = _prepare_agent_chat_generation_entity(
            app_model=app_model,
            app_model_config=app_model_config,
            end_user=end_user,
            conversation=conversation,
            inputs=inputs,
            query=query,
            files=files,
            parent_message_id=parent_message_id,
            auto_generate_name=auto_generate_name,
            streaming=True,
        )
        conversation, message = await _init_agent_chat_records_async(
            session=session,
            application_generate_entity=application_generate_entity,
            end_user=end_user,
            conversation=conversation,
        )
        await _prefetch_agent_chat_memory_async(
            session=session,
            conversation=conversation,
            app_model=app_model,
            app_model_config=app_model_config,
        )

    _set_runtime_cache(message, "_cached_app_model_config", app_model_config)
    _set_runtime_cache(message, "_cached_agent_thought_count", 0)

    return _PreparedAgentChatRun(
        app_model=app_model,
        end_user=end_user,
        conversation=conversation,
        message=message,
        application_generate_entity=application_generate_entity,
    )


def _start_native_public_workflow(
    *,
    prepared: _PreparedWorkflowRun,
    streaming: bool,
) -> Mapping[str, Any] | Iterator[str]:
    """Start workflow execution after async request-stage loading has completed."""

    app_model = prepared.app_model
    workflow = prepared.workflow
    end_user = prepared.end_user
    application_generate_entity = prepared.application_generate_entity
    runtime_session_maker = configured_sync_session_factory.get_session_maker()

    workflow_execution_repository = DifyCoreRepositoryFactory.create_workflow_execution_repository(
        session_factory=runtime_session_maker,
        user=end_user,
        app_id=application_generate_entity.app_config.app_id,
        triggered_from=WorkflowRunTriggeredFrom.APP_RUN,
    )
    workflow_node_execution_repository = DifyCoreRepositoryFactory.create_workflow_node_execution_repository(
        session_factory=runtime_session_maker,
        user=end_user,
        app_id=application_generate_entity.app_config.app_id,
        triggered_from=WorkflowNodeExecutionTriggeredFrom.WORKFLOW_RUN,
    )

    queue_manager = WorkflowAppQueueManager(
        task_id=application_generate_entity.task_id,
        user_id=end_user.id,
        invoke_from=InvokeFrom.WEB_APP,
        app_mode=app_model.mode,
    )
    workflow_owner_id = workflow.created_by
    if workflow_owner_id is None:
        raise bad_request("app_unavailable", "App unavailable, please refresh and try again.")
    pause_state_config = PauseStateLayerConfig(
        session_factory=runtime_session_maker,
        state_owner_user_id=workflow_owner_id,
    )

    worker = threading.Thread(
        target=_run_workflow_runner,
        kwargs={
            "application_generate_entity": application_generate_entity,
            "workflow": workflow,
            "end_user": end_user,
            "queue_manager": queue_manager,
            "workflow_execution_repository": workflow_execution_repository,
            "workflow_node_execution_repository": workflow_node_execution_repository,
            "pause_state_config": pause_state_config,
        },
        daemon=True,
    )
    worker.start()

    response = WorkflowAppGenerateTaskPipeline(
        application_generate_entity=application_generate_entity,
        workflow=workflow,
        queue_manager=queue_manager,
        user=end_user,
        draft_var_saver_factory=BaseAppGenerator._get_draft_var_saver_factory(InvokeFrom.WEB_APP, end_user),
        stream=streaming,
    ).process()
    converted = WorkflowAppGenerateResponseConverter.convert(response=response, invoke_from=InvokeFrom.WEB_APP)
    return cast(Mapping[str, Any] | Iterator[str], BaseAppGenerator.convert_to_event_stream(converted))


async def _run_native_public_workflow(
    *,
    context: WebappContext,
    inputs: dict[str, Any],
    files: list[dict[str, Any]] | None,
    streaming: bool,
    workflow_id: str | None = None,
) -> Mapping[str, Any] | Iterator[str]:
    prepared = await _prepare_native_public_workflow(
        context=context,
        inputs=inputs,
        files=files,
        streaming=streaming,
        workflow_id=workflow_id,
    )
    await _save_workflow_app_log_async(
        application_generate_entity=prepared.application_generate_entity,
        workflow=prepared.workflow,
        created_by_role=CreatorUserRole.END_USER,
        created_by=prepared.end_user.id,
    )
    if streaming:
        return _start_native_public_workflow(
            prepared=prepared,
            streaming=True,
        )
    return await asyncio.to_thread(
        _start_native_public_workflow,
        prepared=prepared,
        streaming=False,
    )


async def _prepare_native_public_workflow(
    *,
    context: WebappContext,
    inputs: dict[str, Any],
    files: list[dict[str, Any]] | None,
    streaming: bool,
    workflow_id: str | None = None,
) -> _PreparedWorkflowRun:
    """Load workflow request state on `AsyncSession` before entering sync runners."""

    async with db.session_context() as session:
        app_model = await session.get(FastAPIApp, context.app.id)
        workflow = await session.scalar(
            select(FastAPIWorkflow).where(
                FastAPIWorkflow.id == (workflow_id or context.app.workflow_id),
                FastAPIWorkflow.app_id == context.app.id,
            )
        )
        end_user = await session.get(FastAPIEndUser, context.end_user.id)

    if app_model is None or workflow is None or end_user is None:
        raise bad_request("app_unavailable", "App unavailable, please refresh and try again.")

    application_generate_entity = _prepare_workflow_generation_entity(
        app_model=app_model,
        workflow=workflow,
        end_user=end_user,
        inputs=inputs,
        files=files,
        streaming=streaming,
    )
    return _PreparedWorkflowRun(
        app_model=app_model,
        workflow=workflow,
        end_user=end_user,
        application_generate_entity=application_generate_entity,
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
        await session.commit()
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
        await session.commit()
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
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(20)
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
        await session.commit()


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


def _generate_completion_with_shared_generator(
    *,
    app: FastAPIApp,
    end_user: FastAPIEndUser,
    args: dict[str, Any],
    streaming: bool,
) -> Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None]:
    return cast(
        Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None],
        CompletionAppGenerator().generate(app, end_user, args, InvokeFrom.WEB_APP, streaming),
    )


def _generate_more_like_this_with_shared_generator(
    *,
    app: FastAPIApp,
    end_user: FastAPIEndUser,
    message_id: str,
    streaming: bool,
) -> Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None]:
    return cast(
        Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None],
        CompletionAppGenerator().generate_more_like_this(app, message_id, end_user, InvokeFrom.WEB_APP, streaming),
    )


def _generate_chat_with_shared_generator(
    *,
    app: FastAPIApp,
    end_user: FastAPIEndUser,
    args: dict[str, Any],
    streaming: bool,
) -> Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None]:
    return cast(
        Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None],
        ChatAppGenerator().generate(app, end_user, args, InvokeFrom.WEB_APP, streaming),
    )


async def _next_chunk(iterator: Iterator[LLMResultChunk]) -> LLMResultChunk | None:
    def _next() -> LLMResultChunk | None:
        try:
            return next(iterator)
        except StopIteration:
            return None

    return await asyncio.to_thread(_next)


class AsyncWebGenerationService:
    """FastAPI-native public generation entrypoints.

    Completion, chat, workflow, advanced-chat, and agent-chat now stay on
    direct FastAPI service paths.
    """

    @classmethod
    async def run_completion(
        cls,
        *,
        context: WebappContext,
        inputs: dict[str, Any],
        query: str,
        files: list[dict[str, Any]] | None,
        streaming: bool,
    ) -> Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None]:
        args = {
            "inputs": inputs,
            "query": query,
            "files": files or [],
            "auto_generate_name": False,
        }
        return await asyncio.to_thread(
            _generate_completion_with_shared_generator,
            app=context.app,
            end_user=context.end_user,
            args=args,
            streaming=streaming,
        )

    @classmethod
    async def run_more_like_this(
        cls,
        *,
        context: WebappContext,
        message_id: str,
        streaming: bool,
    ) -> Mapping[str, Any] | Generator[Mapping[str, Any] | str, None, None]:
        return await asyncio.to_thread(
            _generate_more_like_this_with_shared_generator,
            app=context.app,
            end_user=context.end_user,
            message_id=message_id,
            streaming=streaming,
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
    ) -> (
        Mapping[str, Any]
        | Generator[Mapping[str, Any] | str, None, None]
        | Iterator[str]
    ):
        if context.app.mode == context.app.mode.CHAT:
            args = {
                "inputs": inputs,
                "query": query,
                "files": files or [],
                "conversation_id": conversation_id,
                "parent_message_id": parent_message_id,
                "auto_generate_name": False,
            }
            return await asyncio.to_thread(
                _generate_chat_with_shared_generator,
                app=context.app,
                end_user=context.end_user,
                args=args,
                streaming=streaming,
            )

        if context.app.mode == context.app.mode.ADVANCED_CHAT:
            return await _run_native_public_advanced_chat(
                context=context,
                inputs=inputs,
                query=query,
                files=files,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                auto_generate_name=False,
                streaming=streaming,
            )

        if context.app.mode == context.app.mode.AGENT_CHAT:
            if not streaming:
                raise bad_request(
                    "response_mode_required",
                    "Agent chat apps require response_mode='streaming'.",
                )
            return await _run_native_public_agent_chat(
                context=context,
                inputs=inputs,
                query=query,
                files=files,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                auto_generate_name=False,
            )

        raise service_unavailable(
            "generation_backend_unavailable",
            "Async-native chat generation is unavailable for this app mode.",
        )

    @classmethod
    async def run_workflow(
        cls,
        *,
        context: WebappContext,
        inputs: dict[str, Any],
        files: list[dict[str, Any]] | None,
        streaming: bool,
        workflow_id: str | None = None,
    ) -> Mapping[str, Any] | Iterator[str]:
        return await _run_native_public_workflow(
            context=context,
            inputs=inputs,
            files=files,
            streaming=streaming,
            workflow_id=workflow_id,
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
