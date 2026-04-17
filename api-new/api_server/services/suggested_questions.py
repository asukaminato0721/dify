"""FastAPI-native suggested-questions service."""

from __future__ import annotations

from sqlalchemy import select

from api_server.errors import bad_request, not_found
from api_server.models.app import AppMode, AppModelConfig, Conversation, Message
from api_server.services.webapp_context import WebappContext
from constants import UUID_NIL
from core.llm_generator.llm_generator import LLMGenerator
from core.model_manager import ModelManager
from extensions.ext_database import db
from graphon.model_runtime.entities.model_entities import ModelType


class SuggestedQuestionsService:
    """Generate suggested follow-up questions for public chat messages."""

    @staticmethod
    def _extract_thread_messages(messages: list[Message]) -> list[Message]:
        thread_messages: list[Message] = []
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

    @staticmethod
    def _format_histories(messages: list[Message]) -> str:
        lines: list[str] = []
        for message in messages:
            lines.append(f"Human: {message.query}")
            lines.append(f"Assistant: {message.answer}")
        return "\n".join(lines)

    @classmethod
    async def get_suggested_questions(cls, *, context: WebappContext, message_id: str) -> list[str]:
        async with db.session_context() as session:
            message = await session.scalar(
                select(Message)
                .where(
                    Message.id == message_id,
                    Message.app_id == context.app.id,
                    Message.from_source == "api",
                    Message.from_end_user_id == context.end_user.id,
                )
                .limit(1)
            )
            if message is None:
                raise not_found("message_not_found", "Message not found.")

            conversation = await session.scalar(
                select(Conversation)
                .where(
                    Conversation.id == message.conversation_id,
                    Conversation.app_id == context.app.id,
                    Conversation.from_source == "api",
                    Conversation.from_end_user_id == context.end_user.id,
                    Conversation.is_deleted.is_(False),
                )
                .limit(1)
            )
            if conversation is None:
                raise not_found("conversation_not_found", "Conversation not found.")

            message_rows = (
                await session.scalars(
                    select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(10)
                )
            ).all()

            app_model_config = None
            if conversation.app_model_config_id:
                app_model_config = await session.scalar(
                    select(AppModelConfig).where(AppModelConfig.id == conversation.app_model_config_id).limit(1)
                )
            if app_model_config is None and context.app_model_config is not None:
                app_model_config = context.app_model_config

        if context.app.mode == AppMode.ADVANCED_CHAT:
            if context.workflow is None:
                return []
            feature = context.workflow.features_dict.get("suggested_questions_after_answer", {"enabled": False})
            if not feature.get("enabled", False):
                raise bad_request(
                    "suggested_questions_after_answer_disabled",
                    "Suggested questions after answer is disabled.",
                )
            model_instance = ModelManager.for_tenant(tenant_id=context.app.tenant_id).get_default_model_instance(
                tenant_id=context.app.tenant_id,
                model_type=ModelType.LLM,
            )
        else:
            if app_model_config is None:
                raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")
            feature_dict = app_model_config.to_feature_dict()
            suggested_questions_config = feature_dict.get("suggested_questions_after_answer", {"enabled": False})
            if not suggested_questions_config.get("enabled", False):
                raise bad_request(
                    "suggested_questions_after_answer_disabled",
                    "Suggested questions after answer is disabled.",
                )
            model_dict = feature_dict.get("model", {})
            provider = model_dict.get("provider")
            model_name = model_dict.get("name")
            if not provider or not model_name:
                raise bad_request("app_unavailable", "App unavailable, please check your app configurations.")
            model_instance = ModelManager.for_tenant(tenant_id=context.app.tenant_id).get_model_instance(
                tenant_id=context.app.tenant_id,
                provider=provider,
                model_type=ModelType.LLM,
                model=model_name,
            )

        thread_messages = cls._extract_thread_messages(list(message_rows))
        histories = cls._format_histories(thread_messages[-3:])
        return list(
            LLMGenerator.generate_suggested_questions_after_answer(
                tenant_id=context.app.tenant_id,
                histories=histories,
            )
        )
