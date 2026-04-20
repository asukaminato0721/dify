from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import pytest

import api_server.services.suggested_questions as suggested_questions_module
from api_server.services.suggested_questions import SuggestedQuestionsService
from graphon.model_runtime.entities.model_entities import ModelType


class _AppStub:
    id: str
    tenant_id: str
    mode: str

    def __init__(self, *, app_id: str, tenant_id: str, mode: str) -> None:
        self.id = app_id
        self.tenant_id = tenant_id
        self.mode = mode


class _EndUserStub:
    id: str

    def __init__(self, *, user_id: str) -> None:
        self.id = user_id


class _FeatureConfigStub:
    features: dict[str, object]

    def __init__(self, *, features: dict[str, object]) -> None:
        self.features = features

    def to_feature_dict(self) -> dict[str, object]:
        return self.features


class _ContextStub:
    app: _AppStub
    end_user: _EndUserStub
    app_model_config: _FeatureConfigStub | None
    workflow: object | None

    def __init__(self, *, app_mode: str, app_model_config: _FeatureConfigStub | None) -> None:
        self.app = _AppStub(app_id="app-1", tenant_id="tenant-1", mode=app_mode)
        self.end_user = _EndUserStub(user_id="end-user-1")
        self.app_model_config = app_model_config
        self.workflow = None


class _MessageStub:
    id: str
    app_id: str
    from_source: str
    from_end_user_id: str
    conversation_id: str
    parent_message_id: str | None
    query: str
    answer: str

    def __init__(
        self,
        *,
        message_id: str,
        app_id: str,
        conversation_id: str,
        user_id: str,
        parent_message_id: str | None,
        query: str,
        answer: str,
    ) -> None:
        self.id = message_id
        self.app_id = app_id
        self.from_source = "api"
        self.from_end_user_id = user_id
        self.conversation_id = conversation_id
        self.parent_message_id = parent_message_id
        self.query = query
        self.answer = answer


class _ConversationStub:
    id: str
    app_id: str
    from_source: str
    from_end_user_id: str
    is_deleted: bool
    app_model_config_id: str | None

    def __init__(self, *, conversation_id: str, app_id: str, user_id: str) -> None:
        self.id = conversation_id
        self.app_id = app_id
        self.from_source = "api"
        self.from_end_user_id = user_id
        self.is_deleted = False
        self.app_model_config_id = None


class _ScalarResultStub:
    rows: list[_MessageStub]

    def __init__(self, *, rows: list[_MessageStub]) -> None:
        self.rows = rows

    def all(self) -> list[_MessageStub]:
        return self.rows


class _SessionStub:
    scalar_results: list[object]
    message_rows: list[_MessageStub]

    def __init__(self, *, scalar_results: list[object], message_rows: list[_MessageStub]) -> None:
        self.scalar_results = scalar_results
        self.message_rows = message_rows

    async def scalar(self, _statement) -> object:
        return self.scalar_results.pop(0)

    async def scalars(self, _statement) -> _ScalarResultStub:
        return _ScalarResultStub(rows=self.message_rows)


class _SessionContextStub:
    session: _SessionStub

    def __init__(self, *, session: _SessionStub) -> None:
        self.session = session

    async def __aenter__(self) -> _SessionStub:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _ModelManagerStub:
    calls: list[tuple[str, object]]

    def __init__(self) -> None:
        self.calls = []

    def get_model_instance(
        self,
        tenant_id: str,
        provider: str,
        model_type: ModelType,
        model: str,
    ) -> object:
        self.calls.append(("get_model_instance", (tenant_id, provider, model_type, model)))
        return object()


def _fake_generate_suggested_questions_after_answer(tenant_id: str, histories: str):
    return iter(["One?", "Two?"])


@pytest.mark.asyncio
async def test_get_suggested_questions_offloads_model_lookup_and_generation() -> None:
    context = _ContextStub(
        app_mode="chat",
        app_model_config=_FeatureConfigStub(
            features={
                "suggested_questions_after_answer": {"enabled": True},
                "model": {"provider": "openai", "name": "gpt-4o"},
            }
        ),
    )
    conversation_id = "conversation-1"
    message_id = "message-1-leaf"
    messages = [
        _MessageStub(
            message_id="message-1-leaf",
            app_id=context.app.id,
            conversation_id=conversation_id,
            user_id=context.end_user.id,
            parent_message_id="message-1-mid",
            query="Latest question",
            answer="Latest answer",
        ),
        _MessageStub(
            message_id="message-1-mid",
            app_id=context.app.id,
            conversation_id=conversation_id,
            user_id=context.end_user.id,
            parent_message_id="message-1-root",
            query="Follow-up question",
            answer="Follow-up answer",
        ),
        _MessageStub(
            message_id="message-1-root",
            app_id=context.app.id,
            conversation_id=conversation_id,
            user_id=context.end_user.id,
            parent_message_id=None,
            query="Root question",
            answer="Root answer",
        ),
    ]
    session = _SessionStub(
        scalar_results=[
            messages[0],
            _ConversationStub(conversation_id=conversation_id, app_id=context.app.id, user_id=context.end_user.id),
        ],
        message_rows=messages,
    )
    model_manager = _ModelManagerStub()
    calls: list[tuple[Callable[..., object], tuple[object, ...], dict[str, object]]] = []

    async def fake_to_thread(
        func: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    with (
        patch.object(suggested_questions_module.asyncio, "to_thread", fake_to_thread),
        patch(
            "api_server.services.suggested_questions.db.session_context",
            return_value=_SessionContextStub(session=session),
        ),
        patch("api_server.services.suggested_questions.ModelManager.for_tenant", return_value=model_manager),
        patch(
            "api_server.services.suggested_questions.LLMGenerator.generate_suggested_questions_after_answer",
            new=_fake_generate_suggested_questions_after_answer,
        ),
    ):
        result = await SuggestedQuestionsService.get_suggested_questions(context=context, message_id=message_id)

    assert result == ["One?", "Two?"]
    assert len(calls) == 2
    assert calls[0][0].__name__ == "get_model_instance"
    assert calls[0][1] == ("tenant-1", "openai", ModelType.LLM, "gpt-4o")
    assert calls[1][0] is _fake_generate_suggested_questions_after_answer
    assert calls[1][1] == (
        "tenant-1",
        "Human: Root question\n"
        "Assistant: Root answer\n"
        "Human: Follow-up question\n"
        "Assistant: Follow-up answer\n"
        "Human: Latest question\n"
        "Assistant: Latest answer",
    )
    assert model_manager.calls == [
        ("get_model_instance", ("tenant-1", "openai", ModelType.LLM, "gpt-4o"))
    ]
