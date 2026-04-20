from __future__ import annotations

import enum
import json
from decimal import Decimal
from datetime import datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from api_server.db import Base, EnumText, LongText, StringUUID
from core.db.session_factory import session_factory as configured_sync_session_factory
from factories import variable_factory
from graphon.file import FileBelongsTo
from graphon.variables import VariableBase


class AppMode(enum.StrEnum):
    COMPLETION = "completion"
    WORKFLOW = "workflow"
    CHAT = "chat"
    ADVANCED_CHAT = "advanced-chat"
    AGENT_CHAT = "agent-chat"
    CHANNEL = "channel"
    RAG_PIPELINE = "rag-pipeline"


class AppStatus(enum.StrEnum):
    NORMAL = "normal"
    ARCHIVED = "archived"


class TenantStatus(enum.StrEnum):
    NORMAL = "normal"
    ARCHIVE = "archive"


class AccountStatus(enum.StrEnum):
    PENDING = "pending"
    UNINITIALIZED = "uninitialized"
    ACTIVE = "active"
    BANNED = "banned"
    CLOSED = "closed"


class TenantAccountRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    NORMAL = "normal"
    DATASET_OPERATOR = "dataset_operator"


class CreatorUserRole(enum.StrEnum):
    ACCOUNT = "account"
    END_USER = "end_user"


class StorageType(enum.StrEnum):
    LOCAL = "local"


class ApiTokenType(enum.StrEnum):
    APP = "app"
    DATASET = "dataset"


class TagType(enum.StrEnum):
    KNOWLEDGE = "knowledge"
    APP = "app"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tenant_pkey"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    plan: Mapped[str] = mapped_column(String(255), default="basic")
    status: Mapped[TenantStatus] = mapped_column(
        EnumText(TenantStatus, length=255),
        server_default=sa.text("'normal'"),
        default=TenantStatus.NORMAL,
    )
    custom_config: Mapped[str | None] = mapped_column(LongText, default=None)

    @property
    def custom_config_dict(self) -> dict[str, Any]:
        if not self.custom_config:
            return {}
        return json.loads(self.custom_config)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_pkey"),
        sa.Index("account_email_idx", "email"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(String(255), default=None)
    password_salt: Mapped[str | None] = mapped_column(String(255), default=None)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    interface_language: Mapped[str | None] = mapped_column(String(255), default=None)
    interface_theme: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    timezone: Mapped[str | None] = mapped_column(String(255), default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True, default=None)
    last_login_ip: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    last_active_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
    )
    status: Mapped[AccountStatus] = mapped_column(
        EnumText(AccountStatus, length=16),
        server_default=sa.text("'active'"),
        default=AccountStatus.ACTIVE,
    )
    initialized_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        onupdate=func.current_timestamp(),
    )


class TenantAccountJoin(Base):
    __tablename__ = "tenant_account_joins"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tenant_account_join_pkey"),
        sa.Index("tenant_account_join_account_id_idx", "account_id"),
        sa.Index("tenant_account_join_tenant_id_idx", "tenant_id"),
        sa.UniqueConstraint("tenant_id", "account_id", name="unique_tenant_account_join"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    account_id: Mapped[str] = mapped_column(StringUUID)
    current: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), default=False)
    role: Mapped[TenantAccountRole] = mapped_column(
        EnumText(TenantAccountRole, length=16),
        server_default="normal",
        default=TenantAccountRole.NORMAL,
    )
    invited_by: Mapped[str | None] = mapped_column(StringUUID, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=func.current_timestamp(),
        nullable=False,
        onupdate=func.current_timestamp(),
    )


class App(Base):
    __tablename__ = "apps"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="app_pkey"),
        sa.Index("app_tenant_id_idx", "tenant_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(LongText, default="")
    mode: Mapped[AppMode] = mapped_column(EnumText(AppMode, length=255))
    icon_type: Mapped[str | None] = mapped_column(String(255), default=None)
    icon: Mapped[str | None] = mapped_column(String(255), default=None)
    icon_background: Mapped[str | None] = mapped_column(String(255), default=None)
    created_by: Mapped[str | None] = mapped_column(StringUUID, default=None)
    app_model_config_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    workflow_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    status: Mapped[AppStatus] = mapped_column(
        EnumText(AppStatus, length=255),
        server_default=sa.text("'normal'"),
        default=AppStatus.NORMAL,
    )
    enable_site: Mapped[bool] = mapped_column(sa.Boolean)
    enable_api: Mapped[bool] = mapped_column(sa.Boolean)
    use_icon_as_answer_icon: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
        default=False,
    )

    @property
    def app_model_config(self) -> "AppModelConfig | None":
        cached_config = getattr(self, "_cached_app_model_config", None)
        if isinstance(cached_config, AppModelConfig):
            return cached_config
        if self.app_model_config_id is None:
            return None
        with configured_sync_session_factory.create_sync_session() as session:
            return session.scalar(select(AppModelConfig).where(AppModelConfig.id == self.app_model_config_id))


class EndUser(Base):
    __tablename__ = "end_users"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="end_user_pkey"),
        sa.Index("end_user_session_id_idx", "session_id", "type"),
        sa.Index("end_user_tenant_session_id_idx", "tenant_id", "session_id", "type"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    type: Mapped[str] = mapped_column(String(255))
    external_user_id: Mapped[str | None] = mapped_column(String(255), default=None)
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    is_anonymous: Mapped[bool] = mapped_column(sa.Boolean, default=True, server_default=sa.text("true"))
    session_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class DefaultEndUserSessionID(enum.StrEnum):
    DEFAULT_SESSION_ID = "DEFAULT-USER"


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="site_pkey"),
        sa.Index("site_app_id_idx", "app_id"),
        sa.Index("site_code_idx", "code", "status"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    title: Mapped[str] = mapped_column(String(255))
    icon_type: Mapped[str | None] = mapped_column(String(255), default=None)
    icon: Mapped[str | None] = mapped_column(String(255), default=None)
    icon_background: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(LongText, default=None)
    default_language: Mapped[str] = mapped_column(String(255))
    chat_color_theme: Mapped[str | None] = mapped_column(String(255), default=None)
    chat_color_theme_inverted: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    copyright: Mapped[str | None] = mapped_column(String(255), default=None)
    privacy_policy: Mapped[str | None] = mapped_column(String(255), default=None)
    show_workflow_steps: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    use_icon_as_answer_icon: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    custom_disclaimer: Mapped[str | None] = mapped_column(LongText, default=None)
    prompt_public: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    status: Mapped[str | None] = mapped_column(String(255), default=None)
    code: Mapped[str | None] = mapped_column(String(255), default=None)


class AppModelConfig(Base):
    __tablename__ = "app_model_configs"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="app_model_config_pkey"),
        sa.Index("app_app_id_idx", "app_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    opening_statement: Mapped[str | None] = mapped_column(LongText, default=None)
    suggested_questions: Mapped[str | None] = mapped_column(LongText, default=None)
    suggested_questions_after_answer: Mapped[str | None] = mapped_column(LongText, default=None)
    speech_to_text: Mapped[str | None] = mapped_column(LongText, default=None)
    text_to_speech: Mapped[str | None] = mapped_column(LongText, default=None)
    more_like_this: Mapped[str | None] = mapped_column(LongText, default=None)
    model: Mapped[str | None] = mapped_column(LongText, default=None)
    user_input_form: Mapped[str | None] = mapped_column(LongText, default=None)
    dataset_query_variable: Mapped[str | None] = mapped_column(String(255), default=None)
    pre_prompt: Mapped[str | None] = mapped_column(LongText, default=None)
    agent_mode: Mapped[str | None] = mapped_column(LongText, default=None)
    sensitive_word_avoidance: Mapped[str | None] = mapped_column(LongText, default=None)
    retriever_resource: Mapped[str | None] = mapped_column(LongText, default=None)
    chat_prompt_config: Mapped[str | None] = mapped_column(LongText, default=None)
    completion_prompt_config: Mapped[str | None] = mapped_column(LongText, default=None)
    dataset_configs: Mapped[str | None] = mapped_column(LongText, default=None)
    external_data_tools: Mapped[str | None] = mapped_column(LongText, default=None)
    file_upload: Mapped[str | None] = mapped_column(LongText, default=None)

    @staticmethod
    def _load_json(raw: str | None, default: Any) -> Any:
        if not raw:
            return default
        return json.loads(raw)

    def to_feature_dict(self) -> dict[str, Any]:
        return {
            "opening_statement": self.opening_statement,
            "suggested_questions": self._load_json(self.suggested_questions, []),
            "suggested_questions_after_answer": self._load_json(
                self.suggested_questions_after_answer,
                {"enabled": False},
            ),
            "speech_to_text": self._load_json(self.speech_to_text, {"enabled": False}),
            "text_to_speech": self._load_json(self.text_to_speech, {"enabled": False}),
            "retriever_resource": self._load_json(self.retriever_resource, {"enabled": True}),
            "annotation_reply": {"enabled": False},
            "more_like_this": self._load_json(self.more_like_this, {"enabled": False}),
            "sensitive_word_avoidance": self._load_json(
                self.sensitive_word_avoidance, {"enabled": False, "type": "", "config": {}}
            ),
            "external_data_tools": self._load_json(self.external_data_tools, []),
            "model": self._load_json(self.model, {}),
            "user_input_form": self._load_json(self.user_input_form, []),
            "dataset_query_variable": self.dataset_query_variable,
            "pre_prompt": self.pre_prompt,
            "agent_mode": self._load_json(
                self.agent_mode,
                {"enabled": False, "strategy": None, "tools": [], "prompt": None},
            ),
            "chat_prompt_config": self._load_json(self.chat_prompt_config, {}),
            "completion_prompt_config": self._load_json(self.completion_prompt_config, {}),
            "dataset_configs": self._load_json(self.dataset_configs, {"retrieval_model": "multiple"}),
            "file_upload": self._load_json(
                self.file_upload,
                {
                    "image": {
                        "enabled": False,
                        "number_limits": 3,
                        "detail": "high",
                        "transfer_methods": ["remote_url", "local_file"],
                    }
                },
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the legacy-compatible app-model-config feature payload."""

        config = self.to_feature_dict()
        config["prompt_type"] = (
            "advanced" if config.get("chat_prompt_config") or config.get("completion_prompt_config") else "simple"
        )
        return config

    @property
    def more_like_this_dict(self) -> dict[str, Any]:
        raw = self.more_like_this
        return json.loads(raw) if raw else {"enabled": False}


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_pkey"),
        sa.Index("workflow_version_idx", "tenant_id", "app_id", "version"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    type: Mapped[str | None] = mapped_column(String(255), default=None)
    version: Mapped[str] = mapped_column(String(255))
    graph: Mapped[str] = mapped_column(LongText)
    features: Mapped[str | None] = mapped_column(LongText, default=None)
    created_by: Mapped[str | None] = mapped_column(StringUUID, default=None)
    environment_variables: Mapped[str | None] = mapped_column(LongText, default=None)
    conversation_variables: Mapped[str | None] = mapped_column(LongText, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    @property
    def graph_dict(self) -> dict[str, Any]:
        return json.loads(self.graph) if self.graph else {}

    @property
    def features_dict(self) -> dict[str, Any]:
        features = json.loads(self.features) if self.features else {}
        if features.get("file_upload", {}).get("image", {}).get("enabled", False):
            image = features["file_upload"]["image"]
            features["file_upload"]["enabled"] = True
            features["file_upload"]["number_limits"] = int(image.get("number_limits", 3))
            features["file_upload"]["allowed_file_upload_methods"] = image.get(
                "transfer_methods", ["remote_url", "local_file"]
            )
            features["file_upload"]["allowed_file_types"] = features["file_upload"].get("allowed_file_types", ["image"])
            features["file_upload"]["allowed_file_extensions"] = features["file_upload"].get(
                "allowed_file_extensions", []
            )
            del features["file_upload"]["image"]
        return features

    @property
    def environment_variables_list(self) -> list[dict[str, Any]]:
        if not self.environment_variables:
            return []
        raw_values = json.loads(self.environment_variables)
        if isinstance(raw_values, dict):
            return [value for value in raw_values.values() if isinstance(value, dict)]
        if isinstance(raw_values, list):
            return [value for value in raw_values if isinstance(value, dict)]
        return []

    @property
    def conversation_variables_list(self) -> list[dict[str, Any]]:
        if not self.conversation_variables:
            return []
        raw_values = json.loads(self.conversation_variables)
        if isinstance(raw_values, dict):
            return [value for value in raw_values.values() if isinstance(value, dict)]
        if isinstance(raw_values, list):
            return [value for value in raw_values if isinstance(value, dict)]
        return []

    @property
    def environment_variables_value_objects(self) -> list[VariableBase]:
        return [
            variable_factory.build_environment_variable_from_mapping(mapping)
            for mapping in self.environment_variables_list
        ]

    @property
    def conversation_variables_value_objects(self) -> list[VariableBase]:
        return [
            variable_factory.build_conversation_variable_from_mapping(mapping)
            for mapping in self.conversation_variables_list
        ]

    def user_input_form(self, to_old_structure: bool = False) -> list[Any]:
        if not self.graph:
            return []
        nodes = self.graph_dict.get("nodes", [])
        start_node = next((node for node in nodes if node.get("data", {}).get("type") == "start"), None)
        if not start_node:
            return []
        variables = start_node.get("data", {}).get("variables", [])
        if not to_old_structure:
            return variables
        return [{variable["type"]: variable} for variable in variables]


class ApiToolProvider(Base):
    __tablename__ = "tool_api_providers"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tool_api_provider_pkey"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    icon: Mapped[str] = mapped_column(String(255))


class UploadFile(Base):
    __tablename__ = "upload_files"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="upload_file_pkey"),
        sa.Index("upload_file_tenant_idx", "tenant_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    storage_type: Mapped[str] = mapped_column(String(255), default=StorageType.LOCAL.value)
    key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(sa.Integer)
    extension: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(255), default=None)
    created_by_role: Mapped[str] = mapped_column(String(255), default=CreatorUserRole.END_USER.value)
    created_by: Mapped[str] = mapped_column(StringUUID)
    used: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), default=False)
    used_by: Mapped[str | None] = mapped_column(StringUUID, default=None)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    hash: Mapped[str | None] = mapped_column(String(255), default=None)
    source_url: Mapped[str] = mapped_column(LongText, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="api_token_pkey"),
        sa.Index("api_token_app_id_type_idx", "app_id", "type"),
        sa.Index("api_token_token_idx", "token", "type"),
        sa.Index("api_token_tenant_idx", "tenant_id", "type"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    tenant_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    type: Mapped[ApiTokenType] = mapped_column(EnumText(ApiTokenType, length=16))
    token: Mapped[str] = mapped_column(String(255))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tag_pkey"),
        sa.Index("tag_type_idx", "type"),
        sa.Index("tag_name_idx", "name"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    type: Mapped[TagType] = mapped_column(EnumText(TagType, length=16))
    name: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class TagBinding(Base):
    __tablename__ = "tag_bindings"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tag_binding_pkey"),
        sa.Index("tag_bind_target_id_idx", "target_id"),
        sa.Index("tag_bind_tag_id_idx", "tag_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    tag_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    target_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    created_by: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="conversation_pkey"),
        sa.Index("conversation_app_from_user_idx", "app_id", "from_source", "from_end_user_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    app_model_config_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    model_provider: Mapped[str | None] = mapped_column(String(255), default=None)
    model_id: Mapped[str | None] = mapped_column(String(255), default=None)
    override_model_configs: Mapped[str | None] = mapped_column(LongText, default=None)
    mode: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(LongText, default=None)
    inputs: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    introduction: Mapped[str | None] = mapped_column(LongText, default=None)
    system_instruction: Mapped[str | None] = mapped_column(LongText, default=None)
    system_instruction_tokens: Mapped[int | None] = mapped_column(sa.Integer, default=0)
    status: Mapped[str] = mapped_column(String(255), default="normal")
    invoke_from: Mapped[str | None] = mapped_column(String(255), default=None)
    from_source: Mapped[str] = mapped_column(String(255))
    from_end_user_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    from_account_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    read_account_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    dialogue_count: Mapped[int | None] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    is_deleted: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), default=False)

    @property
    def app(self) -> App | None:
        cached_app = getattr(self, "_cached_app", None)
        if isinstance(cached_app, App):
            return cached_app
        with configured_sync_session_factory.create_sync_session() as session:
            return session.scalar(select(App).where(App.id == self.app_id))

    @property
    def model_config(self) -> dict[str, Any]:
        model_config: dict[str, Any] = {}

        if self.mode == AppMode.ADVANCED_CHAT.value:
            if self.override_model_configs:
                return json.loads(self.override_model_configs)
            return model_config

        if self.override_model_configs:
            override_model_configs = json.loads(self.override_model_configs)
            if isinstance(override_model_configs, dict):
                if "model" in override_model_configs:
                    model_config = dict(override_model_configs)
                else:
                    model_config["configs"] = override_model_configs
        elif self.app_model_config_id:
            cached_config = getattr(self, "_cached_app_model_config", None)
            if isinstance(cached_config, AppModelConfig):
                app_model_config = cached_config
            else:
                with configured_sync_session_factory.create_sync_session() as session:
                    app_model_config = session.scalar(select(AppModelConfig).where(AppModelConfig.id == self.app_model_config_id))
            if app_model_config is not None:
                model_config = app_model_config.to_dict()

        model_config["model_id"] = self.model_id
        model_config["provider"] = self.model_provider
        return model_config


class PinnedConversation(Base):
    __tablename__ = "pinned_conversations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="pinned_conversation_pkey"),
        sa.Index("pinned_conversation_conversation_idx", "app_id", "conversation_id", "created_by_role", "created_by"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    conversation_id: Mapped[str] = mapped_column(StringUUID)
    created_by_role: Mapped[str] = mapped_column(String(255), default=CreatorUserRole.END_USER.value)
    created_by: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="message_pkey"),
        sa.Index("message_conversation_id_idx", "conversation_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    model_provider: Mapped[str | None] = mapped_column(String(255), default=None)
    model_id: Mapped[str | None] = mapped_column(String(255), default=None)
    override_model_configs: Mapped[str | None] = mapped_column(LongText, default=None)
    conversation_id: Mapped[str] = mapped_column(StringUUID)
    inputs: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    query: Mapped[str] = mapped_column(LongText)
    message: Mapped[Any] = mapped_column(sa.JSON, default=None)
    message_tokens: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"), default=0)
    message_unit_price: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 4), default=None)
    message_price_unit: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 7), default=None)
    answer: Mapped[str] = mapped_column(LongText)
    answer_tokens: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"), default=0)
    answer_unit_price: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 4), default=None)
    answer_price_unit: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 7), default=None)
    parent_message_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    provider_response_latency: Mapped[float] = mapped_column(sa.Float, server_default=sa.text("0"), default=0.0)
    total_price: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 7), default=None)
    currency: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[str] = mapped_column(String(255), default="normal")
    error: Mapped[str | None] = mapped_column(LongText, default=None)
    message_metadata: Mapped[str | None] = mapped_column(LongText, default=None)
    invoke_from: Mapped[str | None] = mapped_column(String(255), default=None)
    from_source: Mapped[str] = mapped_column(String(255))
    from_end_user_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    from_account_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    agent_based: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), default=False)
    workflow_run_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    app_mode: Mapped[str | None] = mapped_column(String(255), default=None)

    @property
    def message_metadata_dict(self) -> dict[str, Any]:
        return json.loads(self.message_metadata) if self.message_metadata else {}

    @property
    def app_model_config(self) -> AppModelConfig | None:
        cached_config = getattr(self, "_cached_app_model_config", None)
        if isinstance(cached_config, AppModelConfig):
            return cached_config
        if not self.conversation_id:
            return None
        with configured_sync_session_factory.create_sync_session() as session:
            conversation = session.scalar(select(Conversation).where(Conversation.id == self.conversation_id))
            if conversation is None or conversation.app_model_config_id is None:
                return None
            return session.scalar(select(AppModelConfig).where(AppModelConfig.id == conversation.app_model_config_id))

    @property
    def message_files(self) -> list[dict[str, Any]]:
        from core.app.file_access import DatabaseFileAccessController
        from factories import file_factory

        cached_files = getattr(self, "_cached_message_files", None)
        if isinstance(cached_files, list):
            return cast(list[dict[str, Any]], cached_files)

        access_controller = DatabaseFileAccessController()
        with configured_sync_session_factory.create_sync_session() as session:
            message_files = session.scalars(select(MessageFile).where(MessageFile.message_id == self.id)).all()
            app = session.scalar(select(App).where(App.id == self.app_id))
        if app is None:
            return []

        files: list[dict[str, Any]] = []
        for message_file in message_files:
            file_obj = file_factory.build_from_message_file(
                message_file=message_file,
                tenant_id=app.tenant_id,
                config=None,
                access_controller=access_controller,
            )
            files.append(
                {
                    "belongs_to": message_file.belongs_to or FileBelongsTo.USER.value,
                    "upload_file_id": message_file.upload_file_id or message_file.id,
                    **file_obj.to_dict(),
                }
            )

        return files


class MessageFile(Base):
    __tablename__ = "message_files"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="message_file_pkey"),
        sa.Index("message_file_message_idx", "message_id"),
        sa.Index("message_file_upload_idx", "upload_file_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    message_id: Mapped[str] = mapped_column(StringUUID)
    type: Mapped[str] = mapped_column(String(255))
    transfer_method: Mapped[str | None] = mapped_column(String(255), default=None)
    belongs_to: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(LongText, default=None)
    upload_file_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    created_by_role: Mapped[str] = mapped_column(String(255), default=CreatorUserRole.END_USER.value)
    created_by: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())


class ConversationVariable(Base):
    __tablename__ = "workflow_conversation_variables"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", "conversation_id", name="workflow_conversation_variables_pkey"),
        sa.Index("workflow_conversation_variables_app_id_idx", "app_id"),
        sa.Index("workflow_conversation_variables_conversation_id_idx", "conversation_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    conversation_id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    data: Mapped[str] = mapped_column(LongText)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    @classmethod
    def from_variable(cls, *, app_id: str, conversation_id: str, variable: VariableBase) -> "ConversationVariable":
        return cls(
            id=variable.id,
            app_id=app_id,
            conversation_id=conversation_id,
            data=variable.model_dump_json(),
        )

    def to_variable(self) -> VariableBase:
        return variable_factory.build_conversation_variable_from_mapping(json.loads(self.data))


class MessageFeedback(Base):
    __tablename__ = "message_feedbacks"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="message_feedback_pkey"),
        sa.Index("message_feedback_message_idx", "message_id", "from_source"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    conversation_id: Mapped[str] = mapped_column(StringUUID)
    message_id: Mapped[str] = mapped_column(StringUUID)
    rating: Mapped[str] = mapped_column(String(255))
    from_source: Mapped[str] = mapped_column(String(255))
    content: Mapped[str | None] = mapped_column(LongText, default=None)
    from_end_user_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    from_account_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class MessageAnnotation(Base):
    __tablename__ = "message_annotations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="message_annotation_pkey"),
        sa.Index("message_annotation_app_idx", "app_id"),
        sa.Index("message_annotation_conversation_idx", "conversation_id"),
        sa.Index("message_annotation_message_idx", "message_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    question: Mapped[str] = mapped_column(LongText)
    content: Mapped[str] = mapped_column(LongText)
    account_id: Mapped[str] = mapped_column(StringUUID)
    conversation_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    message_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    hit_count: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"), default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class MessageAgentThought(Base):
    __tablename__ = "message_agent_thoughts"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="message_agent_thought_pkey"),
        sa.Index("message_agent_thought_message_id_idx", "message_id"),
        sa.Index("message_agent_thought_message_chain_id_idx", "message_chain_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    message_id: Mapped[str] = mapped_column(StringUUID)
    position: Mapped[int] = mapped_column(sa.Integer)
    created_by_role: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(StringUUID)
    message_chain_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    thought: Mapped[str | None] = mapped_column(LongText, default=None)
    tool: Mapped[str | None] = mapped_column(LongText, default=None)
    tool_labels_str: Mapped[str] = mapped_column(LongText, default="{}")
    tool_meta_str: Mapped[str] = mapped_column(LongText, default="{}")
    tool_input: Mapped[str | None] = mapped_column(LongText, default=None)
    observation: Mapped[str | None] = mapped_column(LongText, default=None)
    tool_process_data: Mapped[str | None] = mapped_column(LongText, default=None)
    message: Mapped[str | None] = mapped_column(LongText, default=None)
    message_token: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    message_unit_price: Mapped[Decimal | None] = mapped_column(sa.Numeric, default=None)
    message_price_unit: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 7), default=None)
    message_files: Mapped[str | None] = mapped_column(LongText, default=None)
    answer: Mapped[str | None] = mapped_column(LongText, default=None)
    answer_token: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    answer_unit_price: Mapped[Decimal | None] = mapped_column(sa.Numeric, default=None)
    answer_price_unit: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 7), default=None)
    tokens: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    total_price: Mapped[Decimal | None] = mapped_column(sa.Numeric, default=None)
    currency: Mapped[str | None] = mapped_column(String(255), default=None)
    latency: Mapped[float | None] = mapped_column(sa.Float, default=None)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())

    @property
    def files(self) -> list[Any]:
        return json.loads(self.message_files) if self.message_files else []

    @property
    def tool_labels(self) -> dict[str, Any]:
        try:
            return json.loads(self.tool_labels_str) if self.tool_labels_str else {}
        except Exception:
            return {}


class AppAnnotationHitHistory(Base):
    __tablename__ = "app_annotation_hit_histories"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="app_annotation_hit_histories_pkey"),
        sa.Index("app_annotation_hit_histories_app_idx", "app_id"),
        sa.Index("app_annotation_hit_histories_account_idx", "account_id"),
        sa.Index("app_annotation_hit_histories_annotation_idx", "annotation_id"),
        sa.Index("app_annotation_hit_histories_message_idx", "message_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    annotation_id: Mapped[str] = mapped_column(StringUUID)
    source: Mapped[str] = mapped_column(LongText)
    question: Mapped[str] = mapped_column(LongText)
    account_id: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    score: Mapped[float] = mapped_column(sa.Float, server_default=sa.text("0"))
    message_id: Mapped[str] = mapped_column(StringUUID)
    annotation_question: Mapped[str] = mapped_column(LongText)
    annotation_content: Mapped[str] = mapped_column(LongText)


class AppAnnotationSetting(Base):
    __tablename__ = "app_annotation_settings"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="app_annotation_settings_pkey"),
        sa.Index("app_annotation_settings_app_idx", "app_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    score_threshold: Mapped[float] = mapped_column(sa.Float, server_default=sa.text("0"))
    collection_binding_id: Mapped[str] = mapped_column(StringUUID)
    created_user_id: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_user_id: Mapped[str] = mapped_column(StringUUID)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class SavedMessage(Base):
    __tablename__ = "saved_messages"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="saved_message_pkey"),
        sa.Index("saved_message_message_idx", "app_id", "message_id", "created_by_role", "created_by"),
        sa.Index("saved_message_message_id_idx", "message_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    message_id: Mapped[str] = mapped_column(StringUUID)
    created_by_role: Mapped[str] = mapped_column(String(255), default=CreatorUserRole.END_USER.value)
    created_by: Mapped[str] = mapped_column(StringUUID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.current_timestamp())
