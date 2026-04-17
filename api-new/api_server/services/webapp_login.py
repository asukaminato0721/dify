from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import jwt
from sqlalchemy import func, select

from api_server.errors import forbidden, unauthorized
from api_server.models.app import Account, AccountStatus
from configs import dify_config
from extensions.ext_database import db
from libs.password import compare_password, hash_password


class WebappLoginService:
    """Async account authentication for FastAPI webapp login routes."""

    @staticmethod
    async def authenticate(email: str, password: str) -> Account:
        normalized_email = email.lower()
        async with db.session_context() as session:
            account = await session.scalar(select(Account).where(func.lower(Account.email) == normalized_email).limit(1))

        if account is None:
            raise unauthorized("authentication_failed", "Authentication failed.")
        if account.status == AccountStatus.BANNED:
            raise forbidden("account_banned", "Account is banned.")
        if account.password is None or account.password_salt is None:
            raise unauthorized("authentication_failed", "Authentication failed.")
        if not compare_password(password, account.password, account.password_salt):
            raise unauthorized("authentication_failed", "Authentication failed.")
        return account

    @staticmethod
    def issue_access_token(account: Account) -> str:
        exp_dt = datetime.now(UTC) + timedelta(minutes=dify_config.ACCESS_TOKEN_EXPIRE_MINUTES * 24)
        payload = {
            "sub": "Web API Passport",
            "user_id": account.id,
            "session_id": account.email,
            "token_source": "webapp_login_token",
            "auth_type": "internal",
            "exp": int(exp_dt.timestamp()),
        }
        return jwt.encode(payload, dify_config.SECRET_KEY, algorithm="HS256")

    @staticmethod
    async def get_user_by_email(email: str) -> Account:
        normalized_email = email.lower()
        async with db.session_context() as session:
            account = await session.scalar(select(Account).where(func.lower(Account.email) == normalized_email).limit(1))

        if account is None:
            raise unauthorized("authentication_failed", "Authentication failed.")
        if account.status == AccountStatus.BANNED:
            raise forbidden("account_banned", "Account is banned.")
        return account

    @staticmethod
    def issue_email_code_token(email: str, code: str) -> str:
        exp_dt = datetime.now(UTC) + timedelta(minutes=dify_config.EMAIL_CODE_LOGIN_TOKEN_EXPIRY_MINUTES)
        payload = {
            "sub": "Web Email Code Login",
            "email": email.lower(),
            "code": code,
            "token_source": "email_code_login",
            "exp": int(exp_dt.timestamp()),
        }
        return jwt.encode(payload, dify_config.SECRET_KEY, algorithm="HS256")

    @staticmethod
    def issue_email_code(email: str) -> tuple[str, str]:
        code = "".join(str(secrets.randbelow(10)) for _ in range(6))
        return code, WebappLoginService.issue_email_code_token(email=email, code=code)

    @staticmethod
    def verify_email_code_token(token: str) -> "EmailCodeTokenPayload":
        decoded = jwt.decode(token, dify_config.SECRET_KEY, algorithms=["HS256"])
        email = decoded.get("email")
        code = decoded.get("code")
        token_source = decoded.get("token_source")
        if not isinstance(email, str) or not isinstance(code, str) or token_source != "email_code_login":
            raise unauthorized("invalid_email_code_token", "Invalid token.")
        return {
            "email": email,
            "code": code,
        }


class EmailCodeTokenPayload(TypedDict):
    email: str
    code: str


class ResetPasswordTokenPayload(TypedDict):
    email: str
    code: str
    phase: str


class WebappResetPasswordService:
    """Stateless reset-password flow for the FastAPI webapp routes."""

    @staticmethod
    def issue_reset_password_token(email: str, code: str, *, phase: str) -> str:
        exp_dt = datetime.now(UTC) + timedelta(minutes=dify_config.RESET_PASSWORD_TOKEN_EXPIRY_MINUTES)
        payload = {
            "sub": "Web Reset Password",
            "email": email.lower(),
            "code": code,
            "phase": phase,
            "token_source": "reset_password",
            "exp": int(exp_dt.timestamp()),
        }
        return jwt.encode(payload, dify_config.SECRET_KEY, algorithm="HS256")

    @staticmethod
    def issue_reset_password_code(email: str) -> tuple[str, str]:
        code = "".join(str(secrets.randbelow(10)) for _ in range(6))
        return code, WebappResetPasswordService.issue_reset_password_token(email=email, code=code, phase="verify")

    @staticmethod
    def verify_reset_password_token(token: str) -> ResetPasswordTokenPayload:
        decoded = jwt.decode(token, dify_config.SECRET_KEY, algorithms=["HS256"])
        email = decoded.get("email")
        code = decoded.get("code")
        phase = decoded.get("phase")
        token_source = decoded.get("token_source")
        if (
            not isinstance(email, str)
            or not isinstance(code, str)
            or not isinstance(phase, str)
            or token_source != "reset_password"
        ):
            raise unauthorized("invalid_token", "Invalid token.")
        return {"email": email, "code": code, "phase": phase}

    @staticmethod
    async def update_password(*, email: str, new_password: str) -> None:
        account = await WebappLoginService.get_user_by_email(email)
        salt = secrets.token_bytes(16)
        password_hashed = hash_password(new_password, salt)

        async with db.session_context() as session:
            merged_account = await session.scalar(select(Account).where(Account.id == account.id).limit(1))
            if merged_account is None:
                raise unauthorized("authentication_failed", "Authentication failed.")
            merged_account.password = base64.b64encode(password_hashed).decode()
            merged_account.password_salt = base64.b64encode(salt).decode()
            async with session.begin():
                session.add(merged_account)
