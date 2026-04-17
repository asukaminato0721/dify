from __future__ import annotations

from sqlalchemy import select

from api_server.errors import bad_request
from api_server.models.app import Site
from extensions.ext_database import db


class AppLookupService:
    """Minimal app/site lookup service for public FastAPI endpoints."""

    @staticmethod
    async def get_app_id_by_code(app_code: str) -> str:
        async with db.session_context() as session:
            site = await session.scalar(select(Site).where(Site.code == app_code).limit(1))

        if site is None:
            raise bad_request("app_not_found", f"App with code {app_code} not found.")
        return site.app_id
