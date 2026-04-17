from __future__ import annotations

import jwt
from fastapi import Request
from fastapi.security import APIKeyCookie, APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from configs import dify_config

_webapp_access_token_cookie = APIKeyCookie(name="webapp_access_token", auto_error=False)
_webapp_passport_header = APIKeyHeader(name="X-App-Passport", auto_error=False)
_webapp_bearer = HTTPBearer(auto_error=False)


def _extract_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


async def extract_webapp_access_token(request: Request) -> str | None:
    cookie_token = await _webapp_access_token_cookie(request)
    bearer_token = _extract_bearer_token(await _webapp_bearer(request))
    return cookie_token or bearer_token


async def extract_webapp_passport(app_code: str, request: Request) -> str | None:
    cookie_token = request.cookies.get(f"passport-{app_code}")
    header_token = await _webapp_passport_header(request)
    bearer_token = _extract_bearer_token(await _webapp_bearer(request))
    return cookie_token or header_token or bearer_token


def verify_passport(token: str) -> dict[str, object]:
    return jwt.decode(token, dify_config.SECRET_KEY, algorithms=["HS256"])
