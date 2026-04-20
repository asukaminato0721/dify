import hashlib
import logging
from types import SimpleNamespace
from threading import Thread, Timer
from typing import Any, cast, Union

from sqlalchemy import select, update

from api_server.models.app import Conversation as FastAPIConversation
from api_server.models.app import MessageAnnotation as FastAPIMessageAnnotation
from api_server.models.app import MessageFile as FastAPIMessageFile
from api_server.models.app import UploadFile as FastAPIUploadFile
from configs import dify_config
from core.app.entities.app_invoke_entities import (
    AdvancedChatAppGenerateEntity,
    AgentChatAppGenerateEntity,
    ChatAppGenerateEntity,
    CompletionAppGenerateEntity,
)
from core.app.entities.queue_entities import (
    QueueAnnotationReplyEvent,
    QueueMessageFileEvent,
    QueueRetrieverResourcesEvent,
)
from core.app.entities.task_entities import (
    AnnotationReply,
    AnnotationReplyAccount,
    EasyUITaskState,
    MessageFileStreamResponse,
    MessageReplaceStreamResponse,
    MessageStreamResponse,
    StreamEvent,
    WorkflowTaskState,
)
from core.app.task_pipeline.message_file_utils import MessageFileInfoDict, prepare_file_dict
from core.db.session_factory import session_factory
from core.llm_generator.llm_generator import LLMGenerator
from core.tools.signature import sign_tool_file
from graphon.file import FileTransferMethod
from extensions.ext_redis import redis_client
from models.enums import MessageFileBelongsTo
from models.model import MessageAnnotation
from services.annotation_service import AppAnnotationService

logger = logging.getLogger(__name__)


class MessageCycleManager:
    def __init__(
        self,
        *,
        application_generate_entity: Union[
            ChatAppGenerateEntity,
            CompletionAppGenerateEntity,
            AgentChatAppGenerateEntity,
            AdvancedChatAppGenerateEntity,
        ],
        task_state: Union[EasyUITaskState, WorkflowTaskState],
    ):
        self._application_generate_entity = application_generate_entity
        self._task_state = task_state
        self._message_has_file: set[str] = set()
        self._message_end_files: dict[str, list[MessageFileInfoDict]] = {}

    def get_message_event_type(self, message_id: str) -> StreamEvent:
        if message_id in self._message_has_file:
            return StreamEvent.MESSAGE_FILE

        return StreamEvent.MESSAGE

    def _load_message_file(self, event: QueueMessageFileEvent) -> FastAPIMessageFile | None:
        if event.message_id and event.url is not None and event.type:
            return FastAPIMessageFile(
                id=event.message_file_id,
                message_id=event.message_id,
                url=event.url,
                type=event.type,
                transfer_method=event.transfer_method,
                upload_file_id=event.upload_file_id,
                belongs_to=event.belongs_to or MessageFileBelongsTo.USER.value,
            )

        with session_factory.create_sync_session() as session:
            return session.scalar(select(FastAPIMessageFile).where(FastAPIMessageFile.id == event.message_file_id))

    def _cache_message_end_file(self, message_file: FastAPIMessageFile) -> None:
        upload_files_map: dict[str, FastAPIUploadFile] = {}
        transfer_method = getattr(message_file, "transfer_method", None)
        upload_file_id = getattr(message_file, "upload_file_id", None)
        if transfer_method == FileTransferMethod.LOCAL_FILE and upload_file_id:
            with session_factory.create_sync_session() as session:
                upload_file = session.scalar(select(FastAPIUploadFile).where(FastAPIUploadFile.id == upload_file_id))
            if upload_file is not None:
                upload_files_map[upload_file.id] = upload_file

        file_info = prepare_file_dict(message_file, cast(dict[str, Any], upload_files_map))
        self._message_end_files.setdefault(message_file.message_id, []).append(file_info)

    def get_cached_message_end_files(self, message_id: str) -> list[MessageFileInfoDict] | None:
        files = self._message_end_files.get(message_id)
        if not files:
            return None
        return list(files)

    def seed_message_end_files(self, message_id: str, files: list[MessageFileInfoDict]) -> None:
        """Prime cached message-end files from async request-stage prefetched data."""

        if not files:
            return
        self._message_end_files[message_id] = list(files)

    def generate_conversation_name(self, *, conversation_id: str, query: str) -> Thread | None:
        """
        Generate conversation name.
        :param conversation_id: conversation id
        :param query: query
        :return: thread
        """
        if isinstance(self._application_generate_entity, CompletionAppGenerateEntity):
            return None

        is_first_message = self._application_generate_entity.is_new_conversation
        extras = self._application_generate_entity.extras
        auto_generate_conversation_name = extras.get("auto_generate_conversation_name", True)

        thread: Thread | None = None
        if auto_generate_conversation_name and is_first_message:
            # start generate thread
            # time.sleep not block other logic
            thread = Timer(
                1,
                self._generate_conversation_name_worker,
                kwargs={"conversation_id": conversation_id, "query": query},
            )
            thread.daemon = True
            thread.start()

        if is_first_message:
            self._application_generate_entity.is_new_conversation = False

        return thread

    def _generate_conversation_name_worker(self, conversation_id: str, query: str) -> None:
        app_config = self._application_generate_entity.app_config
        if str(app_config.app_mode) == "completion":
            return

        query_hash = hashlib.md5(query.encode()).hexdigest()[:16]
        cache_key = f"conv_name:{conversation_id}:{query_hash}"

        cached_name = redis_client.get(cache_key)
        if cached_name:
            name = cached_name.decode("utf-8")
        else:
            try:
                name = LLMGenerator.generate_conversation_name(
                    app_config.tenant_id,
                    query,
                    conversation_id,
                    app_config.app_id,
                )
                redis_client.setex(cache_key, 3600, name)
            except Exception:
                if dify_config.DEBUG:
                    logger.exception("generate conversation name failed, conversation_id: %s", conversation_id)
                name = query[:47] + "..." if len(query) > 50 else query

        with session_factory.get_sync_session_maker().begin() as session:
            session.execute(
                update(FastAPIConversation)
                .where(FastAPIConversation.id == conversation_id)
                .values(name=name)
            )

    def handle_annotation_reply(self, event: QueueAnnotationReplyEvent) -> SimpleNamespace | MessageAnnotation | None:
        """
        Handle annotation reply.
        :param event: event
        :return:
        """
        if event.content is not None and event.account_id is not None:
            account_name = event.account_name if event.account_name else "Dify user"
            self._task_state.metadata.annotation_reply = AnnotationReply(
                id=event.message_annotation_id,
                account=AnnotationReplyAccount(
                    id=event.account_id,
                    name=account_name,
                ),
            )
            return SimpleNamespace(content=event.content)

        annotation = AppAnnotationService.get_annotation_by_id(event.message_annotation_id)
        if annotation:
            account = annotation.account
            account_name = getattr(account, "name", None)
            self._task_state.metadata.annotation_reply = AnnotationReply(
                id=annotation.id,
                account=AnnotationReplyAccount(
                    id=annotation.account_id,
                    name=account_name if isinstance(account_name, str) and account_name else "Dify user",
                ),
            )

            return annotation

        return None

    def handle_retriever_resources(self, event: QueueRetrieverResourcesEvent):
        """
        Handle retriever resources.
        :param event: event
        :return:
        """
        if not self._application_generate_entity.app_config.additional_features:
            raise ValueError("Additional features not found")
        if self._application_generate_entity.app_config.additional_features.show_retrieve_source:
            merged_resources = [r for r in self._task_state.metadata.retriever_resources or [] if r]
            existing_ids = {(r.dataset_id, r.document_id) for r in merged_resources if r.dataset_id and r.document_id}

            # Add new unique resources from the event
            for resource in event.retriever_resources or []:
                if not resource:
                    continue

                is_duplicate = (
                    resource.dataset_id
                    and resource.document_id
                    and (resource.dataset_id, resource.document_id) in existing_ids
                )

                if not is_duplicate:
                    merged_resources.append(resource)

            for i, resource in enumerate(merged_resources, 1):
                resource.position = i

            self._task_state.metadata.retriever_resources = merged_resources

    def message_file_to_stream_response(self, event: QueueMessageFileEvent) -> MessageFileStreamResponse | None:
        """
        Message file to stream response.
        :param event: event
        :return:
        """
        message_file = self._load_message_file(event)

        if message_file and message_file.url is not None:
            self._message_has_file.add(message_file.message_id)
            self._cache_message_end_file(message_file)

            # get tool file id
            tool_file_id = message_file.url.split("/")[-1]
            # trim extension
            tool_file_id = tool_file_id.split(".")[0]

            # get extension
            if "." in message_file.url:
                extension = f".{message_file.url.split('.')[-1]}"
                if len(extension) > 10:
                    extension = ".bin"
            else:
                extension = ".bin"
            # add sign url to local file
            if message_file.url.startswith("http"):
                url = message_file.url
            else:
                url = sign_tool_file(tool_file_id=tool_file_id, extension=extension)

            return MessageFileStreamResponse(
                task_id=self._application_generate_entity.task_id,
                id=message_file.id,
                type=message_file.type,
                belongs_to=message_file.belongs_to or MessageFileBelongsTo.USER.value,
                url=url,
            )

        return None

    def message_to_stream_response(
        self,
        answer: str,
        message_id: str,
        from_variable_selector: list[str] | None = None,
        event_type: StreamEvent | None = None,
    ) -> MessageStreamResponse:
        """
        Message to stream response.
        :param answer: answer
        :param message_id: message id
        :return:
        """
        return MessageStreamResponse(
            task_id=self._application_generate_entity.task_id,
            id=message_id,
            answer=answer,
            from_variable_selector=from_variable_selector,
            event=event_type or StreamEvent.MESSAGE,
        )

    def message_replace_to_stream_response(self, answer: str, reason: str = "") -> MessageReplaceStreamResponse:
        """
        Message replace to stream response.
        :param answer: answer
        :return:
        """
        return MessageReplaceStreamResponse(
            task_id=self._application_generate_entity.task_id, answer=answer, reason=reason
        )
