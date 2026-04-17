from __future__ import annotations

import enum
from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from api_server.db import TypeBase
from api_server.models.app import Account, AccountStatus, Tenant, TenantAccountJoin, TenantAccountRole


class DifySetup(TypeBase):
    """Minimal setup model used by the async bootstrap endpoints."""

    __tablename__ = "dify_setups"
    __table_args__ = (
        sa.PrimaryKeyConstraint("version", name="dify_setup_pkey"),
        {"extend_existing": True},
    )

    version: Mapped[str] = mapped_column(String(255), nullable=False)
    setup_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        init=False,
    )
