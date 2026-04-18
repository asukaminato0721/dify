from __future__ import annotations

import json
from typing import Any

import api_server.models.app as app_models
from api_server.models.app import App, AppMode, AppModelConfig
from core.app.apps.chat.app_config_manager import ChatAppConfigManager
from core.app.apps.completion.app_config_manager import CompletionAppConfigManager


def _build_app_model_config() -> AppModelConfig:
    return AppModelConfig(
        id="config-1",
        app_id="app-1",
        opening_statement="Hello",
        model=json.dumps({"provider": "openai", "name": "gpt-4o-mini", "mode": "chat", "completion_params": {}}),
        file_upload=json.dumps({"enabled": False}),
        dataset_configs=json.dumps({"retrieval_model": "multiple"}),
        sensitive_word_avoidance=json.dumps({"enabled": False, "type": "", "config": {}}),
        text_to_speech=json.dumps({"enabled": False}),
        speech_to_text=json.dumps({"enabled": False}),
        suggested_questions_after_answer=json.dumps({"enabled": False}),
        retriever_resource=json.dumps({"enabled": True}),
        more_like_this=json.dumps({"enabled": False}),
        agent_mode=json.dumps({"enabled": False, "tools": [], "strategy": "router"}),
        user_input_form=json.dumps([]),
        pre_prompt="You are helpful.",
    )


class _SessionStub:
    def __init__(self, scalar_result: object | None) -> None:
        self._scalar_result = scalar_result

    def __enter__(self) -> "_SessionStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def scalar(self, _stmt: object) -> object | None:
        return self._scalar_result


def test_chat_config_manager_accepts_local_fastapi_models() -> None:
    app = App(
        id="app-1",
        tenant_id="tenant-1",
        name="Chat App",
        description="",
        mode=AppMode.CHAT,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id="config-1",
        workflow_id=None,
        status="normal",
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
    config = _build_app_model_config()

    app_config = ChatAppConfigManager.get_app_config(app, config)

    assert app_config.app_id == "app-1"
    assert app_config.app_mode == AppMode.CHAT


def test_completion_config_manager_accepts_local_fastapi_models() -> None:
    app = App(
        id="app-1",
        tenant_id="tenant-1",
        name="Completion App",
        description="",
        mode=AppMode.COMPLETION,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id="config-1",
        workflow_id=None,
        status="normal",
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
    config = _build_app_model_config()

    app_config = CompletionAppConfigManager.get_app_config(app, config)

    assert app_config.app_id == "app-1"
    assert app_config.app_mode == AppMode.COMPLETION


def test_local_app_exposes_app_model_config_property() -> None:
    app = App(
        id="app-1",
        tenant_id="tenant-1",
        name="App",
        description="",
        mode=AppMode.CHAT,
        icon_type=None,
        icon=None,
        icon_background=None,
        created_by=None,
        app_model_config_id="config-1",
        workflow_id=None,
        status="normal",
        enable_site=True,
        enable_api=True,
        use_icon_as_answer_icon=False,
    )
    config = _build_app_model_config()
    original_create_session = app_models.configured_sync_session_factory.create_session
    app_models.configured_sync_session_factory.create_session = lambda: _SessionStub(config)  # type: ignore[assignment]
    try:
        result = app.app_model_config
    finally:
        app_models.configured_sync_session_factory.create_session = original_create_session

    assert result is config


def test_local_app_model_config_more_like_this_dict_uses_json_payload() -> None:
    config = _build_app_model_config()

    assert config.more_like_this_dict == {"enabled": False}
