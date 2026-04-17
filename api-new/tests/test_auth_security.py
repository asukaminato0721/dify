from __future__ import annotations

from starlette.requests import Request

from api_server.auth import extract_webapp_access_token, extract_webapp_passport


async def test_extract_webapp_access_token_reads_bearer_credentials() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/login/status",
            "headers": [(b"authorization", b"Bearer test-access-token")],
            "query_string": b"",
        }
    )

    assert await extract_webapp_access_token(request) == "test-access-token"


async def test_extract_webapp_passport_prefers_dynamic_cookie_name() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/site",
            "headers": [(b"cookie", b"passport-demo-app=test-passport-token")],
            "query_string": b"",
        }
    )

    assert await extract_webapp_passport("demo-app", request) == "test-passport-token"
