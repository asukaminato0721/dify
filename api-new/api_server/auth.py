from __future__ import annotations

import jwt
from fastapi import Request

from configs import dify_config


def extract_webapp_access_token(request: Request) -> str | None:
    cookie_token = request.cookies.get("webapp_access_token")
    auth_header = request.headers.get("Authorization")
    bearer_token: str | None = None
    if auth_header and " " in auth_header:
        auth_scheme, auth_token = auth_header.split(None, 1)
        if auth_scheme.lower() == "bearer":
            bearer_token = auth_token
    return cookie_token or bearer_token


def extract_webapp_passport(app_code: str, request: Request) -> str | None:
    cookie_token = request.cookies.get(f"passport-{app_code}")
    header_token = request.headers.get("X-App-Passport")
    auth_header = request.headers.get("Authorization")
    bearer_token: str | None = None
    if auth_header and " " in auth_header:
        auth_scheme, auth_token = auth_header.split(None, 1)
        if auth_scheme.lower() == "bearer":
            bearer_token = auth_token
    return cookie_token or header_token or bearer_token


def verify_passport(token: str) -> dict[str, object]:
    return jwt.decode(token, dify_config.SECRET_KEY, algorithms=["HS256"])
