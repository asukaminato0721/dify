from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from main import app


async def test_health_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ping_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/console/api/ping")

    assert response.status_code == 200
    assert response.json() == {"result": "pong"}


async def test_system_features_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/system-features")

    assert response.status_code == 200
    payload = response.json()
    assert "app_dsl_version" in payload
    assert "enable_email_password_login" in payload


async def test_webapp_access_mode_defaults_to_public_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/webapp/access-mode")

    assert response.status_code == 200
    assert response.json() == {"accessMode": "public"}


async def test_webapp_permission_defaults_to_true_when_enterprise_disabled() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-App-Code": "demo-app"},
    ) as client:
        response = await client.get("/api/webapp/permission", params={"appId": "demo-id"})

    assert response.status_code == 200
    assert response.json() == {"result": True}


async def test_site_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/site")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_remote_file_info_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/remote-files/https%3A%2F%2Fexample.com%2Ftest.txt")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_remote_file_upload_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/remote-files/upload", json={"url": "https://example.com/test.txt"})

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_file_upload_requires_passport() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "missing_passport"


async def test_passport_requires_app_code() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/passport")

    assert response.status_code == 401
    assert response.json()["code"] == "missing_app_code"


async def test_login_status_without_app_code() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/login/status")

    assert response.status_code == 200
    assert response.json() == {"logged_in": False, "app_logged_in": False}


async def test_login_is_rejected_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/login", json={"email": "user@example.com", "password": "abc12345"})

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


async def test_email_code_login_is_rejected_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/email-code-login", json={"email": "user@example.com"})

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


async def test_forgot_password_is_rejected_when_enterprise_disabled() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"
