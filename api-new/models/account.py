from __future__ import annotations

import enum
import json
from dataclasses import field
from datetime import datetime
from typing import Optional, TypedDict
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import DateTime, String, func, select
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import deprecated

from flask_login import UserMixin

from ._session import (
    async_scalar,
    async_scalars_all,
    legacy_scalar,
    with_async_session,
    with_legacy_sync_session,
)
from .base import TypeBase
from .types import EnumText, LongText, StringUUID


class TenantAccountRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    NORMAL = "normal"
    DATASET_OPERATOR = "dataset_operator"

    @staticmethod
    def is_valid_role(role: str) -> bool:
        if not role:
            return False
        return role in {
            TenantAccountRole.OWNER,
            TenantAccountRole.ADMIN,
            TenantAccountRole.EDITOR,
            TenantAccountRole.NORMAL,
            TenantAccountRole.DATASET_OPERATOR,
        }

    @staticmethod
    def is_privileged_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {TenantAccountRole.OWNER, TenantAccountRole.ADMIN}

    @staticmethod
    def is_admin_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role == TenantAccountRole.ADMIN

    @staticmethod
    def is_non_owner_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {
            TenantAccountRole.ADMIN,
            TenantAccountRole.EDITOR,
            TenantAccountRole.NORMAL,
            TenantAccountRole.DATASET_OPERATOR,
        }

    @staticmethod
    def is_editing_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {TenantAccountRole.OWNER, TenantAccountRole.ADMIN, TenantAccountRole.EDITOR}

    @staticmethod
    def is_dataset_edit_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {
            TenantAccountRole.OWNER,
            TenantAccountRole.ADMIN,
            TenantAccountRole.EDITOR,
            TenantAccountRole.DATASET_OPERATOR,
        }


class AccountStatus(enum.StrEnum):
    PENDING = "pending"
    UNINITIALIZED = "uninitialized"
    ACTIVE = "active"
    BANNED = "banned"
    CLOSED = "closed"


class Account(UserMixin, TypeBase):
    __tablename__ = "accounts"
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="account_pkey"), sa.Index("account_email_idx", "email"))

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(String(255), default=None)
    password_salt: Mapped[str | None] = mapped_column(String(255), default=None)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    interface_language: Mapped[str | None] = mapped_column(String(255), default=None)
    interface_theme: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    timezone: Mapped[str | None] = mapped_column(String(255), default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_login_ip: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    status: Mapped[AccountStatus] = mapped_column(
        EnumText(AccountStatus, length=16), server_default=sa.text("'active'"), default=AccountStatus.ACTIVE
    )
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False, onupdate=func.current_timestamp()
    )

    role: TenantAccountRole | None = field(default=None, init=False)
    _current_tenant: "Tenant | None" = field(default=None, init=False)

    @property
    def is_password_set(self) -> bool:
        return self.password is not None

    @property
    def current_tenant(self) -> Tenant | None:
        return self._current_tenant

    @current_tenant.setter
    def current_tenant(self, tenant: "Tenant") -> None:
        def load_tenant_context(session) -> tuple[TenantAccountJoin | None, Tenant]:
            tenant_join_query = select(TenantAccountJoin).where(
                TenantAccountJoin.tenant_id == tenant.id, TenantAccountJoin.account_id == self.id
            )
            tenant_join = session.scalar(tenant_join_query)
            tenant_query = select(Tenant).where(Tenant.id == tenant.id)
            # TODO: A workaround to reload the tenant with `expire_on_commit=False`, allowing
            # access to it after the session has been closed.
            # This prevents `DetachedInstanceError` when accessing the tenant outside
            # the session's lifecycle.
            # (The `tenant` argument is typically loaded by `db.session` without the
            # `expire_on_commit=False` flag, meaning its lifetime is tied to the web
            # request's lifecycle.)
            tenant_reloaded = session.scalars(tenant_query).one()
            return tenant_join, tenant_reloaded

        tenant_join, tenant_reloaded = with_legacy_sync_session(load_tenant_context)

        if tenant_join:
            self.role = TenantAccountRole(tenant_join.role)
            self._current_tenant = tenant_reloaded
            return
        self._current_tenant = None

    async def aload_current_tenant(self, tenant: "Tenant") -> Tenant | None:
        """Resolve and cache tenant membership without using the sync fallback."""

        tenant_join = await async_scalar(
            select(TenantAccountJoin).where(
                TenantAccountJoin.tenant_id == tenant.id,
                TenantAccountJoin.account_id == self.id,
            )
        )
        tenant_reloaded = await async_scalar(select(Tenant).where(Tenant.id == tenant.id))
        if isinstance(tenant_join, TenantAccountJoin) and isinstance(tenant_reloaded, Tenant):
            self.role = TenantAccountRole(tenant_join.role)
            self._current_tenant = tenant_reloaded
            return tenant_reloaded

        self._current_tenant = None
        self.role = None
        return None

    @property
    def current_tenant_id(self) -> str | None:
        return self._current_tenant.id if self._current_tenant else None

    def set_tenant_id(self, tenant_id: str) -> None:
        query = (
            select(Tenant, TenantAccountJoin)
            .where(Tenant.id == tenant_id)
            .where(TenantAccountJoin.tenant_id == Tenant.id)
            .where(TenantAccountJoin.account_id == self.id)
        )

        def load_tenant(session):
            tenant_account_join = session.execute(query).first()
            if not tenant_account_join:
                return None
            tenant, join = tenant_account_join
            return tenant, join

        tenant_account_join = with_legacy_sync_session(load_tenant)
        if tenant_account_join is None:
            return
        tenant, join = tenant_account_join
        self.role = TenantAccountRole(join.role)
        self._current_tenant = tenant

    async def aset_tenant_id(self, tenant_id: str) -> None:
        async def load_tenant(session):
            result = await session.execute(
                select(Tenant, TenantAccountJoin)
                .where(Tenant.id == tenant_id)
                .where(TenantAccountJoin.tenant_id == Tenant.id)
                .where(TenantAccountJoin.account_id == self.id)
            )
            return result.first()

        tenant_and_join = await with_async_session(load_tenant)
        if not tenant_and_join:
            return
        tenant, join = tenant_and_join
        self.role = TenantAccountRole(join.role)
        self._current_tenant = tenant

    @property
    def current_role(self) -> TenantAccountRole | None:
        return self.role

    def get_status(self) -> AccountStatus:
        return self.status

    @classmethod
    def get_by_openid(cls, provider: str, open_id: str) -> Account | None:
        account_integrate = with_legacy_sync_session(
            lambda session: session.execute(
                select(AccountIntegrate).where(
                    AccountIntegrate.provider == provider,
                    AccountIntegrate.open_id == open_id,
                )
            ).scalar_one_or_none()
        )
        if account_integrate:
            account = legacy_scalar(select(Account).where(Account.id == account_integrate.account_id))
            return account if isinstance(account, Account) else None
        return None

    @classmethod
    async def aget_by_openid(cls, provider: str, open_id: str) -> Account | None:
        account_integrate = await async_scalar(
            select(AccountIntegrate).where(AccountIntegrate.provider == provider, AccountIntegrate.open_id == open_id)
        )
        if isinstance(account_integrate, AccountIntegrate):
            account = await async_scalar(select(Account).where(Account.id == account_integrate.account_id))
            return account if isinstance(account, Account) else None
        return None

    # check current_user.current_tenant.current_role in ['admin', 'owner']
    @property
    def is_admin_or_owner(self) -> bool:
        return TenantAccountRole.is_privileged_role(self.role)

    @property
    def is_admin(self) -> bool:
        return TenantAccountRole.is_admin_role(self.role)

    @property
    @deprecated("Use has_edit_permission instead.")
    def is_editor(self) -> bool:
        """Determines if the account has edit permissions in their current tenant (workspace).

        This property checks if the current role has editing privileges, which includes:
        - `OWNER`
        - `ADMIN`
        - `EDITOR`

        Note: This checks for any role with editing permission, not just the 'EDITOR' role specifically.
        """
        return self.has_edit_permission

    @property
    def has_edit_permission(self) -> bool:
        """Determines if the account has editing permissions in their current tenant (workspace).

        This property checks if the current role has editing privileges, which includes:
        - `OWNER`
        - `ADMIN`
        - `EDITOR`
        """
        return TenantAccountRole.is_editing_role(self.role)

    @property
    def is_dataset_editor(self) -> bool:
        return TenantAccountRole.is_dataset_edit_role(self.role)

    @property
    def is_dataset_operator(self) -> bool:
        return self.role == TenantAccountRole.DATASET_OPERATOR


class TenantStatus(enum.StrEnum):
    NORMAL = "normal"
    ARCHIVE = "archive"


class TenantCustomConfigDict(TypedDict, total=False):
    remove_webapp_brand: bool
    replace_webapp_logo: str | None


class Tenant(TypeBase):
    __tablename__ = "tenants"
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="tenant_pkey"),)

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    name: Mapped[str] = mapped_column(String(255))
    encrypt_public_key: Mapped[str | None] = mapped_column(LongText, default=None)
    plan: Mapped[str] = mapped_column(String(255), server_default=sa.text("'basic'"), default="basic")
    status: Mapped[TenantStatus] = mapped_column(
        EnumText(TenantStatus, length=255), server_default=sa.text("'normal'"), default=TenantStatus.NORMAL
    )
    custom_config: Mapped[str | None] = mapped_column(LongText, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), init=False, onupdate=func.current_timestamp()
    )

    def get_accounts(self) -> list[Account]:
        accounts = with_legacy_sync_session(
            lambda session: list(
                session.scalars(
                    select(Account).where(
                        Account.id == TenantAccountJoin.account_id, TenantAccountJoin.tenant_id == self.id
                    )
                ).all()
            )
        )
        return accounts

    async def aget_accounts(self) -> list[Account]:
        accounts = await async_scalars_all(
            select(Account).where(Account.id == TenantAccountJoin.account_id, TenantAccountJoin.tenant_id == self.id)
        )
        return [account for account in accounts if isinstance(account, Account)]

    @property
    def custom_config_dict(self) -> TenantCustomConfigDict:
        return json.loads(self.custom_config) if self.custom_config else {}

    @custom_config_dict.setter
    def custom_config_dict(self, value: TenantCustomConfigDict) -> None:
        self.custom_config = json.dumps(value)


class TenantAccountJoin(TypeBase):
    __tablename__ = "tenant_account_joins"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tenant_account_join_pkey"),
        sa.Index("tenant_account_join_account_id_idx", "account_id"),
        sa.Index("tenant_account_join_tenant_id_idx", "tenant_id"),
        sa.UniqueConstraint("tenant_id", "account_id", name="unique_tenant_account_join"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    account_id: Mapped[str] = mapped_column(StringUUID)
    current: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"), default=False)
    role: Mapped[TenantAccountRole] = mapped_column(
        EnumText(TenantAccountRole, length=16), server_default="normal", default=TenantAccountRole.NORMAL
    )
    invited_by: Mapped[str | None] = mapped_column(StringUUID, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False, onupdate=func.current_timestamp()
    )


class AccountIntegrate(TypeBase):
    __tablename__ = "account_integrates"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_integrate_pkey"),
        sa.UniqueConstraint("account_id", "provider", name="unique_account_provider"),
        sa.UniqueConstraint("provider", "open_id", name="unique_provider_open_id"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    account_id: Mapped[str] = mapped_column(StringUUID)
    provider: Mapped[str] = mapped_column(String(16))
    open_id: Mapped[str] = mapped_column(String(255))
    encrypted_token: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, init=False, onupdate=func.current_timestamp()
    )


class InvitationCodeStatus(enum.StrEnum):
    UNUSED = "unused"
    USED = "used"


class InvitationCode(TypeBase):
    __tablename__ = "invitation_codes"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="invitation_code_pkey"),
        sa.Index("invitation_codes_batch_idx", "batch"),
        sa.Index("invitation_codes_code_idx", "code", "status"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, init=False)
    batch: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(32))
    status: Mapped[InvitationCodeStatus] = mapped_column(
        EnumText(InvitationCodeStatus, length=16),
        server_default=sa.text("'unused'"),
        default=InvitationCodeStatus.UNUSED,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    used_by_tenant_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    used_by_account_id: Mapped[str | None] = mapped_column(StringUUID, default=None)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=sa.func.current_timestamp(), nullable=False, init=False
    )


class TenantPluginPermission(TypeBase):
    class InstallPermission(enum.StrEnum):
        EVERYONE = "everyone"
        ADMINS = "admins"
        NOBODY = "noone"

    class DebugPermission(enum.StrEnum):
        EVERYONE = "everyone"
        ADMINS = "admins"
        NOBODY = "noone"

    __tablename__ = "account_plugin_permissions"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_plugin_permission_pkey"),
        sa.UniqueConstraint("tenant_id", name="unique_tenant_plugin"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    install_permission: Mapped[InstallPermission] = mapped_column(
        EnumText(InstallPermission, length=16),
        nullable=False,
        server_default="everyone",
        default=InstallPermission.EVERYONE,
    )
    debug_permission: Mapped[DebugPermission] = mapped_column(
        EnumText(DebugPermission, length=16), nullable=False, server_default="noone", default=DebugPermission.NOBODY
    )


class TenantPluginAutoUpgradeStrategy(TypeBase):
    class StrategySetting(enum.StrEnum):
        DISABLED = "disabled"
        FIX_ONLY = "fix_only"
        LATEST = "latest"

    class UpgradeMode(enum.StrEnum):
        ALL = "all"
        PARTIAL = "partial"
        EXCLUDE = "exclude"

    __tablename__ = "tenant_plugin_auto_upgrade_strategies"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tenant_plugin_auto_upgrade_strategy_pkey"),
        sa.UniqueConstraint("tenant_id", name="unique_tenant_plugin_auto_upgrade_strategy"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID, insert_default=lambda: str(uuid4()), default_factory=lambda: str(uuid4()), init=False
    )
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    strategy_setting: Mapped[StrategySetting] = mapped_column(
        EnumText(StrategySetting, length=16),
        nullable=False,
        server_default="fix_only",
        default=StrategySetting.FIX_ONLY,
    )
    upgrade_mode: Mapped[UpgradeMode] = mapped_column(
        EnumText(UpgradeMode, length=16), nullable=False, server_default="exclude", default=UpgradeMode.EXCLUDE
    )
    exclude_plugins: Mapped[list[str]] = mapped_column(sa.JSON, nullable=False, default_factory=list)
    include_plugins: Mapped[list[str]] = mapped_column(sa.JSON, nullable=False, default_factory=list)
    upgrade_time_of_day: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), init=False, onupdate=func.current_timestamp()
    )
