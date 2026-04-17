from __future__ import annotations

import base64
import datetime
import os
import re
import secrets
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, func, select

from api_server.errors import bad_request, forbidden, unauthorized
from api_server.models.bootstrap import Account, AccountStatus, DifySetup, Tenant, TenantAccountJoin, TenantAccountRole
from configs import dify_config
from constants.languages import get_valid_language, language_timezone_mapping
from extensions.ext_database import db
from libs.password import hash_password, valid_password

EMAIL_PATTERN = re.compile(r"^[\w\.!#$%&'*+\-/=?^_`{|}~]+@([\w-]+\.)+[\w-]{2,}$")


def naive_utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


@dataclass(slots=True)
class SetupStatus:
    step: Literal["not_started", "finished"]
    setup_at: str | None = None


class BootstrapService:
    """Async bootstrap workflow for init validation and first-time setup."""

    @staticmethod
    def validate_email(email: str) -> str:
        if EMAIL_PATTERN.match(email) is None:
            raise bad_request("invalid_email", f"{email} is not a valid email.")
        return email.lower()

    @staticmethod
    async def get_setup_status() -> SetupStatus:
        if dify_config.EDITION != "SELF_HOSTED":
            return SetupStatus(step="finished")

        async with db.session_context() as session:
            setup_state = await session.scalar(select(DifySetup).limit(1))

        if setup_state is None:
            return SetupStatus(step="not_started")
        return SetupStatus(step="finished", setup_at=setup_state.setup_at.isoformat())

    @staticmethod
    async def get_tenant_count() -> int:
        async with db.session_context() as session:
            count = await session.scalar(select(func.count()).select_from(Tenant))
        return int(count or 0)

    @staticmethod
    async def get_init_validate_status(is_init_validated: bool) -> bool:
        if dify_config.EDITION != "SELF_HOSTED":
            return True

        if is_init_validated:
            return True
        return BootstrapService._get_init_password() is None

    @staticmethod
    def validate_init_password(password: str, expected_password: str | None) -> None:
        if expected_password is None:
            return
        if not secrets.compare_digest(password, expected_password):
            raise unauthorized(
                "init_validate_failed",
                "Init validation failed. Please check the password and try again.",
            )

    @staticmethod
    async def setup(
        *,
        email: str,
        name: str,
        password: str,
        language: str | None,
        ip_address: str,
    ) -> None:
        normalized_email = BootstrapService.validate_email(email)
        valid_password(password)

        existing_status = await BootstrapService.get_setup_status()
        if existing_status.step == "finished":
            raise forbidden(
                "already_setup",
                "Dify has been successfully installed. Please refresh the page or return to the dashboard homepage.",
            )

        if await BootstrapService.get_tenant_count() > 0:
            raise forbidden(
                "already_setup",
                "Dify has been successfully installed. Please refresh the page or return to the dashboard homepage.",
            )

        interface_language = get_valid_language(language)
        salt = secrets.token_bytes(16)
        password_hashed = hash_password(password, salt)

        account = Account(
            name=name,
            email=normalized_email,
            password=base64.b64encode(password_hashed).decode(),
            password_salt=base64.b64encode(salt).decode(),
            interface_language=interface_language,
            interface_theme="light",
            timezone=language_timezone_mapping.get(interface_language, "UTC"),
            last_login_ip=ip_address,
            initialized_at=naive_utc_now(),
            status=AccountStatus.ACTIVE,
        )
        tenant = Tenant(name=f"{name}'s Workspace")

        async with db.session_context() as session:
            try:
                async with session.begin():
                    session.add(account)
                    session.add(tenant)
                    await session.flush()

                    session.add(
                        TenantAccountJoin(
                            tenant_id=tenant.id,
                            account_id=account.id,
                            role=TenantAccountRole.OWNER,
                            current=True,
                        )
                    )
                    session.add(DifySetup(version=dify_config.project.version))
            except Exception:
                await session.rollback()
                await BootstrapService._cleanup_failed_setup(session)
                raise

    @staticmethod
    async def _cleanup_failed_setup(session) -> None:
        async with session.begin():
            await session.execute(delete(DifySetup))
            await session.execute(delete(TenantAccountJoin))
            await session.execute(delete(Account))
            await session.execute(delete(Tenant))

    @staticmethod
    def _get_init_password() -> str | None:
        init_password = os.environ.get("INIT_PASSWORD")
        if init_password:
            return init_password
        return None
