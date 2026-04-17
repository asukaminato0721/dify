from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api_server.db import Base, EnumText, LongText, StringUUID


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


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="tenant_pkey"),)

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
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="account_pkey"), sa.Index("account_email_idx", "email"))

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
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(LongText, default="")
    mode: Mapped[AppMode] = mapped_column(EnumText(AppMode, length=255))
    icon_type: Mapped[str | None] = mapped_column(String(255), default=None)
    icon: Mapped[str | None] = mapped_column(String(255), default=None)
    icon_background: Mapped[str | None] = mapped_column(String(255), default=None)
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


class EndUser(Base):
    __tablename__ = "end_users"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="end_user_pkey"),
        sa.Index("end_user_session_id_idx", "session_id", "type"),
        sa.Index("end_user_tenant_session_id_idx", "tenant_id", "session_id", "type"),
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    type: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(255))


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="site_pkey"),
        sa.Index("site_app_id_idx", "app_id"),
        sa.Index("site_code_idx", "code", "status"),
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
            "suggested_questions_after_answer": self._load_json(self.suggested_questions_after_answer, {"enabled": False}),
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


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_pkey"),
        sa.Index("workflow_version_idx", "tenant_id", "app_id", "version"),
    )

    id: Mapped[str] = mapped_column(StringUUID)
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    app_id: Mapped[str] = mapped_column(StringUUID)
    version: Mapped[str] = mapped_column(String(255))
    graph: Mapped[str] = mapped_column(LongText)
    features: Mapped[str | None] = mapped_column(LongText, default=None)
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
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="tool_api_provider_pkey"),)

    id: Mapped[str] = mapped_column(StringUUID)
    icon: Mapped[str] = mapped_column(String(255))


class UploadFile(Base):
    __tablename__ = "upload_files"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="upload_file_pkey"),
        sa.Index("upload_file_tenant_idx", "tenant_id"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    used: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), default=False)
    used_by: Mapped[str | None] = mapped_column(StringUUID, default=None)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    hash: Mapped[str | None] = mapped_column(String(255), default=None)
    source_url: Mapped[str] = mapped_column(LongText, default="")
